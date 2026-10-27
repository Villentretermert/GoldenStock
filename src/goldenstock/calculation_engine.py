"""Bounded Excel arithmetic over Decimal; no Python eval, files, network or AI."""
import hashlib
import json
import re
from decimal import Context, Decimal, DecimalException, localcontext, ROUND_HALF_EVEN, ROUND_HALF_UP, Underflow, DivisionByZero, InvalidOperation, Overflow

ENGINE = 'gs018-v1'
NUMERIC_POLICY = dict(precision=34, rounding='ROUND_HALF_EVEN', display_rounding='ROUND_HALF_UP',
                      currency_places=2, other_places=6, max_integer_exponent=1000)
TOKEN = re.compile(r"\s*(?:(?P<ref>(?:Model!|'Model'!)?\$?[A-Z]{1,2}\$?[1-9][0-9]{0,2})|(?P<number>(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))|(?P<op>[+*/^()\-]))")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def checksum(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def decimal_text(value):
    if value == 0: return '0'
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def parse_number(text):
    # Decimal strings preserve the caller's value without a JSON float conversion.
    if not isinstance(text, str) or len(text)>80 or not re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?', text):
        raise ValueError('Use a decimal string without separators or exponent notation')
    value = Decimal(text)
    if len(value.as_tuple().digits)>34 or value.copy_abs()>Decimal('1e30') or value.as_tuple().exponent < -18:
        raise ValueError('Input exceeds 34 digits, 18 decimal places or absolute value 1e30')
    return value


def parse_formula(formula):
    """Excel negation precedes powers; equal-precedence operators associate left."""
    if not isinstance(formula, str) or not formula.startswith('=') or len(formula)>500:
        raise ValueError('Invalid or oversized formula')
    body=formula[1:].strip(); tokens=[]; pos=0; refs=[]
    while pos<len(body):
        match=TOKEN.match(body,pos)
        if not match: raise ValueError('Only arithmetic and mapped cell references are supported')
        pos=match.end(); kind=match.lastgroup; value=match[kind]
        if kind=='ref':
            value=value.split('!')[-1].replace('$','')
            if value not in refs: refs.append(value)
        elif kind=='number':
            if Decimal(value) not in (0,1): raise ValueError('Move numeric assumptions into mapped inputs; constants may only be 0 and 1')
        tokens.append((kind,value))
    if not tokens or len(tokens)>100: raise ValueError('Formula is empty or too complex')
    index=0; precedence={'+':1,'-':1,'*':2,'/':2,'^':3}

    def expression(minimum=0):
        nonlocal index
        if index>=len(tokens): raise ValueError('Incomplete formula')
        kind,value=tokens[index];index+=1
        if kind in ('ref','number'): node=(kind,value)
        elif value in ('+','-'): node=('unary',value,expression(4))
        elif value=='(':
            node=expression()
            if index>=len(tokens) or tokens[index][1]!=')': raise ValueError('Unbalanced parentheses')
            index+=1
        else: raise ValueError('Unexpected formula operator')
        while index<len(tokens) and tokens[index][1] in precedence and precedence[tokens[index][1]]>=minimum:
            operator=tokens[index][1]; index+=1
            node=('binary',operator,node,expression(precedence[operator]+1))
        return node

    tree=expression()
    if index!=len(tokens): raise ValueError('Unsupported formula syntax')
    return tree,refs


class CalculationError(ValueError):
    pass


def evaluate(node, values):
    if node[0]=='number': return Decimal(node[1])
    if node[0]=='ref': return values[node[1]]
    if node[0]=='unary':
        value=evaluate(node[2],values)
        return -value if node[1]=='-' else +value
    left,right=evaluate(node[2],values),evaluate(node[3],values)
    op=node[1]
    if op=='+': value=left+right
    elif op=='-': value=left-right
    elif op=='*': value=left*right
    elif op=='/':
        if right==0: raise CalculationError('division_by_zero')
        value=left/right
    else:
        if right!=right.to_integral_value() or abs(right)>1000:
            raise CalculationError('exponent_must_be_integer_between_minus_1000_and_1000')
        if left==0 and right<=0: raise CalculationError('undefined_zero_power')
        value=left**int(right)
    if not value.is_finite() or abs(value)>Decimal('1e60'):
        raise CalculationError('numeric_range_exceeded')
    return value


def calculate(contract, scenarios, checks):
    fields=contract['fields']; by_cell={f['cell']:f for f in fields}
    trees={f['cell']:parse_formula(f['formula'])[0] for f in fields if f['role']!='input'}
    results={}
    context=Context(prec=34,rounding=ROUND_HALF_EVEN,Emin=-60,Emax=60,
                    traps=[Underflow,DivisionByZero,InvalidOperation,Overflow])
    for scenario, inputs in sorted(scenarios.items()):
        values={}; output={}; error=None; check_results=[]
        with localcontext(context):
            for cell in contract['order']:
                field=by_cell[cell]
                try:
                    value=parse_number(inputs[field['key']]['value']) if field['role']=='input' else evaluate(trees[cell],values)
                    values[cell]=value
                    # Display rounding never feeds subsequent formulas or control checks.
                    places=2 if field['unit'] in {'USD','EUR','GBP','RUB'} else 6
                    with localcontext() as display_context:
                        display_context.prec=80
                        displayed=value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
                    output[field['key']]=dict(value=decimal_text(value),display=format(displayed,'f'))
                except (CalculationError,DecimalException) as exc:
                    error=dict(key=field['key'],code=str(exc) if isinstance(exc,CalculationError) else 'numeric_range_or_domain_error')
                    break
            if not error:
                for check in checks:
                    with localcontext() as check_context:
                        check_context.prec=160
                        residual=abs(Decimal(output[check['key']]['value'])-Decimal(check['expected']))
                    check_results.append(dict(check,residual=decimal_text(residual),passed=residual<=Decimal(check['tolerance'])))
        state='blocked' if error or any(not c['passed'] for c in check_results) else ('checks_passed' if checks else 'calculated_without_checks')
        results[scenario]=dict(state=state,values=output,error=error,checks=check_results)
    return dict(engine=ENGINE,numeric_policy=NUMERIC_POLICY,scenarios=results,
                state='blocked' if any(r['state']=='blocked' for r in results.values()) else ('checks_passed' if checks else 'calculated_without_checks'))

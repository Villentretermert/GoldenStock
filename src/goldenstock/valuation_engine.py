"""Versioned equity valuation policies built on the GS-018 Decimal calculator."""
from copy import deepcopy
from decimal import Decimal, localcontext
from goldenstock.calculation_engine import calculate, decimal_text, parse_formula

POLICY='gs019-v1'
METHODS={'ddm':'Dividend discount (common equity)', 'fcfe':'FCFE discount (common equity)',
         'pe':'Price / common earnings', 'pb':'Price / common book equity'}
SENSITIVITY=dict(discount_step='0.01',growth_step='0.005',multiple_factors=['0.8','1','1.2'])


def input_fields(method,currency,year,operating=False):
    fields=[dict(key='shares',unit='count',period='assumption',definition='Common economic shares at valuation date; same unit as the ordinary-share quote')]
    def add(key,unit,period,definition): fields.append(dict(key=key,unit=unit,period=period,definition=definition))
    if method in ('ddm','fcfe'):
        for n in range(1,6):
            add(f'cash_{n}',currency,f'FY{year+n}',
                f'Year {n}: '+('dividends to common shareholders' if method=='ddm' else 'cash available to common shareholders after regulatory capital reinvestment'))
        add('cost_equity','ratio','assumption','Annual cost of equity, not WACC; 0.10 means 10%')
        add('terminal_growth','ratio','assumption','Perpetual annual growth after year five; strictly below cost of equity')
    elif method=='pe':
        add('profit_owners',currency,f'FY{year}','Annual profit attributable to parent shareholders, before preferred dividends')
        add('preferred_dividends',currency,f'FY{year}','Preferred distributions deducted from parent profit; explicit zero if absent')
        add('multiple','multiple','assumption','Comparable P/E on common earnings for the same period and accounting basis')
    elif method=='pb':
        add('equity_total',currency,f'FY{year}','Total consolidated equity including non-controlling interests')
        add('equity_nci',currency,f'FY{year}','Non-controlling equity interests included in total; explicit zero if absent')
        add('equity_preferred',currency,f'FY{year}','Preferred equity included in parent equity; explicit zero if absent')
        add('multiple','multiple','assumption','Comparable P/B on common equity, with consistent definitions')
    else: raise ValueError('Unsupported valuation method')
    if operating:
        for key,unit,definition in [
            ('monthly_revenue',currency,'Revenue for the same month and user perimeter as MAU'),
            ('mau','count','Distinct monthly active users for the specified activity definition'),
            ('cohort_start','count','Users eligible for renewal at the start of the monthly cohort interval'),
            ('cohort_retained','count','Users from that original cohort retained one month later; exclude new users'),
            ('contribution_margin','ratio','Contribution margin after service costs; constant-model assumption'),
            ('monthly_discount','ratio','Monthly discount rate for customer cash flows; not an annual rate')]:
            add(key,unit,'assumption',definition)
    return fields


def contract(method,currency,year,operating=False):
    fields=[];cells={}
    def add(key,unit,period,definition,formula=None):
        cell='B'+str(len(fields)+1);cells[key]=cell
        fields.append(dict(key=key,unit=unit,period=period,definition=definition,cell=cell,
                           role='output' if formula else 'input',formula=formula))
    for f in input_fields(method,currency,year,operating): add(**f)
    def output(key,unit,definition,expression):
        add(key,unit,'assumption',definition,'='+expression.format(**cells))
    if method in ('ddm','fcfe'):
        output('discount_factor_1','ratio','Year-one discount factor','1/(1+{cost_equity})')
        for n in range(2,6):
            output(f'discount_factor_{n}','ratio',f'Year-{n} discount factor',f'{{discount_factor_{n-1}}}/(1+{{cost_equity}})')
        for n in range(1,6): output(f'pv_cash_{n}',currency,f'Present value of year {n}',f'{{cash_{n}}}*{{discount_factor_{n}}}')
        output('terminal_value',currency,'Value at the end of year five','{cash_5}*(1+{terminal_growth})/({cost_equity}-{terminal_growth})')
        output('pv_terminal',currency,'Present value of terminal equity','{terminal_value}*{discount_factor_5}')
        output('equity_value',currency,'Common equity value','{pv_cash_1}+{pv_cash_2}+{pv_cash_3}+{pv_cash_4}+{pv_cash_5}+{pv_terminal}')
        output('terminal_share','ratio','Fraction of equity value from terminal value','{pv_terminal}/{equity_value}')
    elif method=='pe':
        output('common_earnings',currency,'Earnings available to common shareholders','{profit_owners}-{preferred_dividends}')
        output('equity_value',currency,'Common equity value','{common_earnings}*{multiple}')
    else:
        output('common_equity',currency,'Common book equity, reconciled from total equity','{equity_total}-{equity_nci}-{equity_preferred}')
        output('equity_value',currency,'Common equity value','{common_equity}*{multiple}')
    output('per_share',currency,'Value per common economic share','{equity_value}/{shares}')
    if operating:
        output('arpu_monthly',currency,'Monthly revenue per active user','{monthly_revenue}/{mau}')
        output('retention_monthly','ratio','Monthly retention of the original cohort','{cohort_retained}/{cohort_start}')
        output('lifetime_months','count','Expected paid months including the first; constant retention','1/(1-{retention_monthly})')
        output('ltv_contribution',currency,'Contribution LTV before acquisition cost; first payment at month-one end','{arpu_monthly}*{contribution_margin}/(1+{monthly_discount}-{retention_monthly})')
    for f in fields:
        if f['formula']: parse_formula(f['formula'])
    return dict(policy=POLICY,fields=fields,order=[f['cell'] for f in fields])


def bound_number(value):
    # Source calculation decimals retain all digits; manual inputs use the stricter GS-018 input parser.
    number=Decimal(value)
    if not number.is_finite() or number.copy_abs()>Decimal('1e30'):
        raise ValueError('Valuation input is outside the supported numeric range')
    return number


def invalid_inputs(method,values,operating):
    v={k:bound_number(x['value']) for k,x in values.items()}
    errors=[]
    if v['shares']<=0: errors.append('shares_must_be_positive')
    if method in ('ddm','fcfe'):
        if not 0<v['cost_equity']<=1: errors.append('cost_of_equity_must_be_between_zero_and_one')
        if not -1<v['terminal_growth']<v['cost_equity']: errors.append('terminal_growth_must_exceed_minus_one_and_be_below_cost_of_equity')
        if v['cash_5']<=0: errors.append('terminal_year_cash_flow_must_be_positive')
        if method=='ddm' and any(v[f'cash_{n}']<0 for n in range(1,6)): errors.append('dividends_cannot_be_negative')
    else:
        if v['multiple']<=0: errors.append('multiple_must_be_positive')
        if method=='pe':
            if v['preferred_dividends']<0 or v['profit_owners']-v['preferred_dividends']<=0:
                errors.append('pe_requires_positive_common_earnings_and_nonnegative_preferred_dividends')
        elif v['equity_total']-v['equity_nci']-v['equity_preferred']<=0 or v['equity_preferred']<0:
            errors.append('pb_requires_positive_common_equity_and_nonnegative_preferred_equity')
    if operating:
        for key in ('mau','cohort_start','cohort_retained'):
            if v[key]!=v[key].to_integral_value(): errors.append(key+'_must_be_an_integer')
        if v['mau']<=0 or v['cohort_start']<=0: errors.append('mau_and_starting_cohort_must_be_positive')
        if not 0<=v['cohort_retained']<v['cohort_start']: errors.append('retention_must_be_at_least_zero_and_below_one')
        if v['monthly_revenue']<0 or not 0<=v['contribution_margin']<=1 or not 0<=v['monthly_discount']<=1:
            errors.append('invalid_operating_revenue_margin_or_discount')
    return errors


def one(method,structure,values,operating):
    try: errors=invalid_inputs(method,values,operating)
    except ValueError: return dict(state='blocked',errors=['valuation_input_out_of_range'],values={})
    if errors: return dict(state='blocked',errors=errors,values={})
    result=calculate(structure,{'base':values},[],input_parser=bound_number)['scenarios']['base']
    if result['state']=='blocked': return dict(state='blocked',errors=[result['error']['code']],values={})
    if Decimal(result['values']['equity_value']['value'])<=0:
        return dict(state='blocked',errors=['nonpositive_common_equity_value'],values={})
    return dict(state='calculated',errors=[],values=result['values'])


def value_scenarios(payload):
    method=payload['method'];operating=payload['operating'];structure=payload['contract'];scenarios={}
    with localcontext() as ctx:
        ctx.prec=80
        for name,inputs in sorted(payload['scenarios'].items()):
            result=one(method,structure,inputs,operating);points=[]
            if result['state']!='blocked':
                if payload['quote']:
                    price=Decimal(payload['quote']['price'])
                    result['upside']=decimal_text(Decimal(result['values']['per_share']['value'])/price-1)
                if method in ('ddm','fcfe'):
                    variations=[{'cost_equity':Decimal(inputs['cost_equity']['value'])+dk*Decimal(SENSITIVITY['discount_step']),
                        'terminal_growth':Decimal(inputs['terminal_growth']['value'])+dg*Decimal(SENSITIVITY['growth_step'])}
                        for dk in (-1,0,1) for dg in (-1,0,1)]
                else: variations=[{'multiple':Decimal(inputs['multiple']['value'])*Decimal(f)} for f in SENSITIVITY['multiple_factors']]
                for change in variations:
                    amended=deepcopy(inputs)
                    for key,value in change.items(): amended[key]['value']=decimal_text(value)
                    cell=one(method,structure,amended,operating)
                    points.append(dict(inputs={k:decimal_text(v) for k,v in change.items()},state=cell['state'],
                        per_share=cell['values'].get('per_share'),errors=cell['errors']))
            result['sensitivity']=points;scenarios[name]=result
    return dict(policy=POLICY,scenarios=scenarios,sensitivity_policy=SENSITIVITY,
        state='blocked' if any(s['state']=='blocked' for s in scenarios.values()) else 'calculated')

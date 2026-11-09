"""Read-only scenario bounds from saved receipts; no valuation or sensitivity rerun."""
import re
from decimal import Decimal,localcontext,ROUND_HALF_UP

POLICY='gs035-v1'
METHOD_LABELS={'ddm':'DDM','fcfe':'FCFE','pe':'P/E','pb':'P/B'}
METRICS=('per_share','equity_value')


def number(item):
    value=item['value']
    if not isinstance(value,str) or len(value)>200 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',value):
        raise ValueError('Invalid saved value')
    parsed=Decimal(value)
    if not parsed.is_finite() or not 0<parsed<=Decimal('1e60'): raise ValueError('Invalid saved value')
    return parsed


def money(value):
    # Display is independent of ambient precision; exact strings remain in the receipt.
    with localcontext() as ctx:
        ctx.prec=100
        rounded=value.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        return '<0.01' if rounded==0 and value>0 else format(rounded,',.2f')


def summarize(payload,result,inputs_current):
    expected=payload.get('scenarios',{});saved=result.get('scenarios',{})
    summary=dict(policy=POLICY,method=payload.get('method'),currency=payload.get('currency'),
        status='unavailable',reason='incomplete_scenarios',scenario_count=len(expected) if isinstance(expected,dict) else 0,metrics={},
        review_status='historical' if inputs_current is False else 'reviewed_snapshot' if inputs_current is True else 'manual_assumptions')
    if (not isinstance(expected,dict) or not isinstance(saved,dict)
            or payload.get('method') not in METHOD_LABELS or payload.get('currency') not in {'USD','EUR','GBP','RUB'}
            or not 1<=len(expected)<=3 or 'base' not in expected or set(expected)!=set(saved)):
        return summary
    if result.get('state')!='calculated' or any(not isinstance(s,dict) or s.get('state')!='calculated' for s in saved.values()):
        return summary|dict(reason='blocked_scenarios')
    metrics={}
    try:
        for metric in METRICS:
            values={name:number(scenario['values'][metric]) for name,scenario in saved.items()}
            low,high=min(values.values()),max(values.values())
            low_names=sorted(name for name,v in values.items() if v==low)
            high_names=sorted(name for name,v in values.items() if v==high)
            def endpoint(value,names):
                return dict(value=saved[names[0]]['values'][metric]['value'],display=money(value),scenarios=names)
            metrics[metric]=dict(low=endpoint(low,low_names),high=endpoint(high,high_names),
                base=endpoint(values['base'],['base']),same_value=low==high,
                same_display=money(low)==money(high))
    except (KeyError,TypeError,ValueError):
        return summary|dict(reason='invalid_saved_values')
    return summary|dict(status='single' if len(saved)==1 else 'range',reason=None,metrics=metrics)

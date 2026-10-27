"""Deterministic normalization and comparison; never infer missing financial context."""
from datetime import date
from decimal import Decimal, localcontext
import re
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

POLICY = 'gs011-v2-source-rounding'
METRICS = {
    'profit': ('Profit after tax', 'money', 'duration', 'Specify total group or attributable profit; exclude other comprehensive income.'),
    'equity': ('Equity', 'money', 'instant', 'Specify total or attributable equity; regulatory capital is a different measure.'),
    'assets': ('Total assets', 'money', 'instant', 'Total reported assets for the specified accounting basis and perimeter.'),
    'roe': ('ROE', 'ratio', 'duration', 'Specify profit numerator, equity denominator, averaging and annualisation.'),
    'roa': ('ROA', 'ratio', 'duration', 'Specify profit numerator, asset denominator, averaging and annualisation.'),
    'nim': ('Net interest margin', 'ratio', 'duration', 'Specify net interest income, earning assets, averaging and annualisation.'),
    'cost_income': ('Cost / income', 'ratio', 'duration', 'Specify cost and income definitions and excluded adjustments.'),
    'npl': ('NPL ratio', 'ratio', 'instant', 'Specify non-performing loan definition and gross/net loan denominator.'),
    'cost_risk': ('Cost of risk', 'ratio', 'duration', 'Specify impairment numerator, loan denominator and annualisation.'),
    'mau': ('MAU', 'count', 'duration', 'Specify active event, deduplicated user population, product and calendar window.'),
    'ltv': ('LTV', 'money', 'duration', 'Specify cohort, horizon, revenue or contribution basis and discount assumptions. Never infer from missing data.'),
}
SCALES = {'units': Decimal(1), 'thousands': Decimal(1000), 'millions': Decimal(1000000), 'billions': Decimal(1000000000)}


class FactInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: str = Field(min_length=1,max_length=32)
    item_index: int = Field(ge=0,le=49999)
    number_text: str = Field(min_length=1,max_length=80)
    metric: str
    unit: Literal['money','count','fraction','percent','bps']
    scale: Literal['units','thousands','millions','billions']
    currency: str = Field(default='',max_length=3)
    period_kind: Literal['instant','quarter','ytd','year','custom']
    period_start: str = ''
    period_end: date
    scope: Literal['group','holding','bank','segment','unknown']
    scope_detail: str = Field(min_length=1,max_length=160)
    accounting: Literal['IFRS','US_GAAP','local_GAAP','management','unknown']
    definition: str = Field(min_length=3,max_length=400)
    disclosure: Literal['original','restated','unknown'] = 'unknown'
    published_on: str = ''
    supersedes: str = Field(default='',max_length=32)
    rounding: Literal['exact','nearest_reported_digit'] = 'exact'

    @model_validator(mode='after')
    def context(self):
        if self.metric not in METRICS:
            raise ValueError('Unknown metric')
        _,kind,timing,_=METRICS[self.metric]
        if kind=='ratio':
            if self.unit not in {'fraction','percent','bps'} or self.scale!='units' or self.currency:
                raise ValueError('Ratios require fraction, percent or bps, units scale and no currency')
        elif self.unit!=kind:
            raise ValueError('Unit does not match metric')
        if kind=='money' and self.currency not in {'USD','RUB','GBP','EUR','BRL','HKD','CNY','JPY','CHF','MXN','COP'}:
            raise ValueError('Select a supported explicit currency; no FX conversion')
        if kind=='count' and self.currency:
            raise ValueError('Counts have no currency')
        if (timing=='instant') != (self.period_kind=='instant'):
            raise ValueError('Metric requires the appropriate instant or duration period')
        if self.period_kind=='instant':
            if self.period_start:
                raise ValueError('Instant facts have no start date')
        else:
            start=date.fromisoformat(self.period_start)
            self.period_start=start.isoformat()
            if start>self.period_end:
                raise ValueError('Period start is after end')
            days=(self.period_end-start).days+1
            if self.period_kind=='quarter' and not 80<=days<=100:
                raise ValueError('Quarter duration must be 80–100 days')
            if self.period_kind=='year' and not 350<=days<=380:
                raise ValueError('Year duration must be 350–380 days')
            if self.period_kind=='ytd' and days>380:
                raise ValueError('YTD exceeds one financial year')
        if self.published_on:
            self.published_on=date.fromisoformat(self.published_on).isoformat()
        for name in ('definition','scope_detail'):
            value=' '.join(getattr(self,name).split())
            if len(value)<3:
                raise ValueError('Definition and perimeter detail must be meaningful')
            setattr(self,name,value)
        return self


def number(text, unit, scale):
    raw=text.strip().replace('\u2212','-')
    negative=raw.startswith('(') and raw.endswith(')')
    if negative: raw=raw[1:-1].strip()
    percent=raw.endswith('%')
    if percent:
        if unit!='percent': raise ValueError('Percent sign conflicts with selected unit')
        raw=raw[:-1].strip()
    pattern=r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
    if not re.fullmatch(pattern,raw) or (negative and raw[0] in '+-'):
        raise ValueError('Use an unambiguous English number; missing values and footnotes are not numbers')
    if len(raw.replace(',','').replace('.','').lstrip('+-'))>28:
        raise ValueError('Number exceeds precision limit')
    with localcontext() as ctx:
        ctx.prec=50
        value=Decimal(raw.replace(',','')) * (-1 if negative else 1)
        value*=SCALES[scale]
        if unit=='percent': value/=100
        if unit=='bps': value/=10000
        return format(value,'f')


def normalize(data, item):
    raw=item.get('text')
    if raw is None or item.get('merged_follower'):
        raise ValueError('No independently reported value in this item')
    selected=data.number_text
    positions=[m.start() for m in re.finditer(re.escape(selected),raw)]
    if len(positions)!=1:
        raise ValueError('Select a number occurring exactly once in the source item')
    start=positions[0]; end=start+len(selected)
    prefix=raw[:start].rstrip(); suffix=raw[end:].lstrip()
    if (prefix and prefix[-1] in '0123456789.,+-\u2212(') or (suffix and suffix[0] in '0123456789.,%)'):
        raise ValueError('Select the complete number, including sign and percent symbol')
    value=number(selected,data.unit,data.scale)
    if data.metric=='mau' and (Decimal(value)<0 or Decimal(value)!=Decimal(value).to_integral_value()):
        raise ValueError('MAU must be a nonnegative whole count')
    warnings=[]
    if data.scope=='unknown' or data.accounting=='unknown': warnings.append('context_incomplete')
    if data.disclosure=='restated': warnings.append('restatement_requires_review')
    if item.get('formula'): warnings.append('formula_cache_unverified')
    if item.get('method')=='ocr': warnings.append('ocr_requires_review')
    if item.get('hidden_sheet'): warnings.append('hidden_sheet')
    if METRICS[data.metric][1]=='ratio' and not Decimal(0)<=Decimal(value)<=1:
        warnings.append('ratio_outside_zero_to_one')
    # Rounding is explicitly confirmed against the source; never guessed from a display format.
    radius=Decimal(0)
    if data.rounding=='nearest_reported_digit':
        digits=selected.strip().strip('()').strip().rstrip('%').strip().replace(',','')
        decimals=len(digits.split('.')[1]) if '.' in digits else 0
        radius=Decimal(number(format(Decimal(10)**(-decimals),'f'),data.unit,data.scale))/2
    return dict(data.model_dump(mode='json'),value=value,rounding_radius=str(radius),canonical_unit='fraction' if METRICS[data.metric][1]=='ratio' else data.unit,
        selected_span=[start,end],location=item['location'],method=item['method'],confidence=item.get('confidence'),
        warnings=warnings,review_status='unreviewed',policy=POLICY)


def rounding_compatible(left,right):
    with localcontext() as ctx:
        ctx.prec=80
        return abs(Decimal(left['value'])-Decimal(right['value'])) <= Decimal(left.get('rounding_radius','0'))+Decimal(right.get('rounding_radius','0'))


def conflicts(facts):
    """Compare only like-for-like facts; metadata disagreements are warnings, not invented equality."""
    results=[]
    fields=('period_kind','period_start','period_end','scope','scope_detail','accounting','definition','currency','canonical_unit')
    for n,left in enumerate(facts):
        for right in facts[n+1:]:
            if left['metric']!=right['metric']: continue
            differences=[k for k in fields if str(left[k]).casefold()!=str(right[k]).casefold()]
            if differences:
                # Different periods are normal; highlight only matching period-end ambiguities.
                if left['period_end']!=right['period_end']: continue
                kind='context_mismatch'; severity='warning'
            elif left['scope']=='unknown' or left['accounting']=='unknown':
                kind='context_incomplete'; severity='warning'
            elif rounding_compatible(left,right):
                continue
            else:
                kind='value_discrepancy'; severity='blocker' if left['metric'] in {'profit','equity'} else 'warning'
            results.append(dict(left=left['id'],right=right['id'],kind=kind,severity=severity,
                                differences=differences,policy=POLICY))
    return results

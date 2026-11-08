"""Deterministic SEC change identities; no financial inference or valuation writes."""
import hashlib
import json
import re
from datetime import date,datetime,timezone
from decimal import Decimal
from goldenstock.public_sources import CIKS,TAGS

POLICY='gs022-v1'
FORMS={'10-K','10-K/A','10-Q','10-Q/A','20-F','20-F/A','40-F','40-F/A','6-K','6-K/A'}


def encode(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)


def sha(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def accession(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',value): raise ValueError('Invalid accession')
    return value


def filing_url(company,accn):
    accn=accession(accn)
    return f'https://www.sec.gov/Archives/edgar/data/{CIKS[company]}/{accn.replace("-", "")}/{accn}-index.html'


def day(value):
    if not isinstance(value,str): raise ValueError('Date required')
    return date.fromisoformat(value).isoformat()


def number(value):
    if isinstance(value,bool): raise ValueError('Invalid numeric value')
    v=Decimal(str(value))
    if not v.is_finite() or abs(v)>Decimal('1e40'): raise ValueError('Invalid numeric value')
    if v==0: return '0'
    # Formatting without normalize() avoids ambient Decimal context rounding.
    text=format(v,'f')
    if len(text)>160: raise ValueError('Numeric precision limit')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def index(company,kind,raw,now):
    data=json.loads(raw,parse_float=Decimal)
    if int(data['cik'])!=CIKS[company]: raise ValueError('Wrong issuer')
    result={}
    if kind=='submissions':
        recent=data['filings']['recent']
        columns=('accessionNumber','form','filingDate','reportDate','primaryDocument')
        count=len(recent['accessionNumber'])
        # Large banks include many securities prospectuses in recent; filter after validation.
        if count>100000 or any(not isinstance(recent[k],list) or len(recent[k])!=count for k in columns): raise ValueError('Invalid filing columns')
        items=recent.get('items',['']*count)
        if not isinstance(items,list) or len(items)!=count: raise ValueError('Invalid items column')
        for i in range(count):
            form=recent['form'][i]
            if form not in FORMS and not (form in {'8-K','8-K/A'} and any(k in str(items[i]).split(',') for k in ('2.02','4.02'))): continue
            accn=accession(recent['accessionNumber'][i]);doc=recent['primaryDocument'][i]
            if not isinstance(doc,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}',doc) or '..' in doc: raise ValueError('Invalid document name')
            item=dict(accession=accn,form=form,filed=day(recent['filingDate'][i]),
                report_date=day(recent['reportDate'][i]) if recent['reportDate'][i] else '',document=doc,
                items=str(items[i])[:100],url=filing_url(company,accn))
            key=sha(accn)
            if key in result and result[key]!=item: raise ValueError('Conflicting filing identity')
            result[key]=item
    elif kind=='facts':
        earliest=f'{datetime.fromtimestamp(now,timezone.utc).year-3}-01-01';ranks={}
        facts=data['facts']
        for namespace in ('us-gaap','ifrs-full'):
            for tag in TAGS:
                concept=facts.get(namespace,{}).get(tag,{})
                label=concept.get('label');definition=concept.get('description')
                if any(v is not None and (not isinstance(v,str) or len(v)>20000) for v in (label,definition)):
                    raise ValueError('Invalid concept definition')
                for unit,values in concept.get('units',{}).items():
                    if not isinstance(unit,str) or len(unit)>40 or not isinstance(values,list) or len(values)>50000: raise ValueError('Invalid fact unit')
                    for position,value in enumerate(values):
                        if value.get('form') not in FORMS: continue
                        end=day(value['end'])
                        if end<earliest: continue
                        start=day(value['start']) if value.get('start') else ''
                        if start and start>end: raise ValueError('Invalid period')
                        filed=day(value['filed']);accn=accession(value['accn'])
                        item=dict(namespace=namespace,tag=tag,unit=unit,start=start,end=end,
                            label=label,definition=definition,scope='entire_filing_entity',
                            value=number(value['val']),filed=filed,accession=accn,form=value['form'],url=filing_url(company,accn),
                            json_path=f'/facts/{namespace}/{tag}/units/{unit}/{position}')
                        key=sha([namespace,tag,unit,start,end]);rank=(filed,accn)
                        if key not in ranks or rank>ranks[key]: result[key]=item;ranks[key]=rank
                        elif rank==ranks[key] and item['value']!=result[key]['value']: raise ValueError('Ambiguous comparable XBRL facts')
        if len(result)>10000: raise ValueError('Fact index limit')
    else: raise ValueError('Unsupported monitor kind')
    return result


def semantic(kind,item):
    if kind=='facts': return {k:item[k] for k in ('namespace','tag','unit','start','end','value')}
    return item

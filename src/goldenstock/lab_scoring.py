"""Transparent micro-averages, kept separate from blind human judgements."""
from decimal import Decimal
import hashlib
import json
from goldenstock.inference import Proposal
from goldenstock.normalization import METRICS,number

POLICY='gs021-v1'
CONTEXT=('currency','scale','period','perimeter','definition')


def encode(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def numeric(token):
    # Reuse the production parser's rejection of malformed/ambiguous tokens.
    number(token,'percent' if '%' in token else 'money','units')
    value=token.replace(',','').replace('−','-').strip()
    if value.startswith('(') and value.endswith(')'): value='-'+value[1:-1]
    percent=value.endswith('%');value=value.rstrip('%')
    result=Decimal(value)
    if not result.is_finite(): raise ValueError('Non-finite number')
    return result,percent


def metric_key(p):
    return p['evidence_id'],p['metric'],numeric(p['number_text'])


def validate_reference(kind,expected,evidence):
    sources={e['id']:e['text'] for e in evidence}
    if not isinstance(expected,list) or len(expected)>12: raise ValueError('Expected labels must be a list of at most 12 items')
    if kind=='summary':
        if any(not isinstance(x,str) or x not in sources for x in expected) or len(expected)!=len(set(expected)):
            raise ValueError('Summary labels must be unique evidence IDs')
        return sorted(expected)
    normalized=[];seen=set()
    for value in expected:
        p=Proposal.model_validate(value).model_dump()
        if p['metric'] not in METRICS or p['evidence_id'] not in sources or p['quote'] not in sources[p['evidence_id']] or p['number_text'] not in p['quote']:
            raise ValueError('Each reference metric must quote its source and numeric token')
        key=metric_key(p)+(p.get('period'),p.get('perimeter'))
        if key in seen: raise ValueError('Duplicate reference metric')
        seen.add(key);normalized.append(p)
    return sorted(normalized,key=encode)


def counts(kind,expected,output,evidence):
    sources={e['id']:e['text'] for e in evidence}
    items=output.get('claims' if kind=='summary' else 'proposals',[])
    remaining=list(expected)
    result=dict(predicted=len(items),expected=len(expected),matched=0,citations=0,
        context_matched={k:0 for k in CONTEXT},context_total=0)
    for item in items:
        citation=item.get('evidence_id') in sources and bool(item.get('quote')) and item['quote'] in sources[item['evidence_id']]
        result['citations']+=int(citation)
        candidates=[ref for ref in remaining if (item.get('evidence_id')==ref if kind=='summary' else metric_key(item)==metric_key(ref))]
        # Match duplicate values one-to-one, preferring the closest labelled context.
        match=max(candidates,key=lambda ref:sum(item.get(k)==ref.get(k) for k in CONTEXT)) if candidates and kind=='proposals' else next(iter(candidates),None)
        if match is not None and citation:
            remaining.remove(match);result['matched']+=1
            if kind=='proposals':
                result['context_total']+=1
                for key in CONTEXT: result['context_matched'][key]+=int(item.get(key)==match.get(key))
    return result


def aggregate(rows):
    totals={k:sum(r[k] for r in rows) for k in ('predicted','expected','matched','citations','context_total')}
    def ratio(n,d): return round(n/d,6) if d else None
    p=ratio(totals['matched'],totals['predicted']);r=ratio(totals['matched'],totals['expected'])
    return dict(totals,precision=p,recall=r,f1=ratio(2*totals['matched'],totals['predicted']+totals['expected']),
        citation_precision=ratio(totals['citations'],totals['predicted']),
        context_accuracy={k:ratio(sum(v['context_matched'][k] for v in rows),totals['context_total']) for k in CONTEXT})

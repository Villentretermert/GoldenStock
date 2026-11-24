"""Opt-in synthetic context probes; run in worker with an idle queue, no facts saved."""
import argparse
import json
import time
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.ai_resources import DeviceGuard
from goldenstock.config import get_settings
from goldenstock.db import make_engine
from goldenstock.inference import OllamaProvider, InferenceError
from goldenstock.models import AIRun, Company

CASES = [
    dict(id='three_metrics', text='Total assets: 1,200. Net profit: (120). ROE: 12.5%.',
         nearby=['Consolidated group. USD millions; year ended 2025.'],
         expected={'assets':('1,200','USD','millions','2025'),
                   'profit':('(120)','USD','millions','2025'),
                   'roe':('12.5%',None,'percent','2025')}),
    dict(id='missing', text='Net profit: 120.', nearby=[],
         expected={'profit':('120',None,None,None)}),
    dict(id='primary_wins', text='Net profit: 120 EUR thousands, FY 2024. Consolidated group.',
         nearby=['Comparative summary: USD millions, year ended 2025.'],
         expected={'profit':('120','EUR','thousands','2024')}),
    dict(id='conflicting_headers', text='Net profit: 120.',
         nearby=['Statement A: USD millions; year ended 2025.',
                 'Statement B: EUR billions; year ended 2024.'],
         expected={'profit':('120',None,None,None)}, allow_rejection=True),
    dict(id='comparative_years', text='Net profit: 120.',
         nearby=['Consolidated group. USD millions; years ended 2025 and 2024.'],
         expected={'profit':('120','USD','millions',None)}, allow_rejection=True),
    dict(id='other_entity', text='JPMorgan consolidated group. Net profit: 120.',
         nearby=['Unrelated Example Holdings only. EUR millions; year ended 2024.'],
         expected={'profit':('120',None,None,None)}, allow_rejection=True),
]


def matches(proposals, expected):
    if len(proposals) != len(expected) or {p['metric'] for p in proposals} != set(expected):
        return False
    for proposal in proposals:
        number, currency, scale, period = expected[proposal['metric']]
        if (proposal['number_text'],proposal['currency'],proposal['scale']) != (number,currency,scale):
            return False
        if period is None:
            if proposal['period'] is not None: return False
        elif period not in (proposal['period'] or ''): return False
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=('qwen4','qwen_small'),default='qwen4')
    parser.add_argument('--case',choices=[case['id'] for case in CASES])
    args=parser.parse_args()
    failed=False
    for case in CASES:
        if args.case and case['id'] != args.case: continue
        with Session(make_engine(get_settings())) as db,db.begin():
            db.scalar(select(Company).where(Company.id=='sber').with_for_update())
            if db.scalar(select(AIRun.id).where(
                    (AIRun.state.in_(['queued','running']))|(AIRun.lease_until>time.time())).limit(1)):
                raise SystemExit('Wait for the AI queue to be idle')
            adapter=OllamaProvider(get_settings());guard=DeviceGuard(adapter,args.profile,'gpu')
            result={};error=''
            try:
                with guard.execution():
                    guard.receipt['inference_started']=True
                    result=adapter.propose_context([dict(id='synthetic:0',text=case['text'])],
                        [dict(id=f'synthetic-context:{i}',text=text) for i,text in enumerate(case['nearby'])],args.profile)
            except InferenceError as exc: error=str(exc)
            matched=not error and matches(result.get('proposals',[]),case['expected'])
            safely_blocked=case.get('allow_rejection',False) and error=='unsupported_context'
            passed=matched or safely_blocked
            failed |= not passed
            print(json.dumps(dict(case=case['id'],profile=args.profile,matched=matched,
                safely_blocked=safely_blocked,passed=passed,error=error,result=result,execution=guard.receipt,
                scope='Synthetic development probe, not gold, holdout or 95% accuracy')),flush=True)
    return 1 if failed else 0


if __name__=='__main__':
    raise SystemExit(main())

"""Synthetic device probe, run in worker only while the AI queue is idle."""
import json
import time
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.db import make_engine
from goldenstock.models import AIRun,Company
from goldenstock.inference import OllamaProvider,InferenceError
from goldenstock.config import get_settings
from goldenstock.ai_resources import DeviceGuard

# This diagnostic does not save facts or claim measurement of production accuracy.
def probe(device):
    adapter=OllamaProvider(get_settings())
    guard=DeviceGuard(adapter,'qwen4',device)
    error='';result={}
    try:
        with guard.execution():
            guard.receipt['inference_started']=True
            result=adapter.propose([dict(id='synthetic:0',text='Total assets USD 120 million at 31 December 2025. Consolidated group.',location={'page':1})],'qwen4')
    except InferenceError as exc: error=str(exc)
    print(json.dumps(dict(execution=guard.receipt,error=error,proposals=result.get('proposals'),provider_seconds=result.get('seconds'))),flush=True)
    if error: raise SystemExit(1)


# Hold the same scheduling lock as the worker; this opt-in diagnostic must be idle.
with Session(make_engine(get_settings())) as db,db.begin():
    db.scalar(select(Company).where(Company.id=='sber').with_for_update())
    if db.scalar(select(AIRun.id).where((AIRun.state.in_(['queued','running']))|(AIRun.lease_until>time.time())).limit(1)):
        raise SystemExit('Wait for the AI queue to be idle before this diagnostic')
    for device in ('gpu','cpu'): probe(device)

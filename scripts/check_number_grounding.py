"""Opt-in synthetic local Qwen probe; run inside worker only with an idle queue."""
import json
import time
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.ai_resources import DeviceGuard
from goldenstock.config import get_settings
from goldenstock.db import make_engine
from goldenstock.inference import OllamaProvider, InferenceError
from goldenstock.models import AIRun, Company

evidence = [dict(id='synthetic:0', text='Total assets: 1,200. Net profit: (120). ROE: 12.5%.')]
context = [dict(id='synthetic-context:0', text='Consolidated group. USD millions; year ended 2025.')]
expected = {('assets', '1,200'), ('profit', '(120)'), ('roe', '12.5%')}

# The same scheduler lock prevents overlap with user inference. No facts are saved.
with Session(make_engine(get_settings())) as db, db.begin():
    db.scalar(select(Company).where(Company.id == 'sber').with_for_update())
    if db.scalar(select(AIRun.id).where(
            (AIRun.state.in_(['queued', 'running'])) | (AIRun.lease_until > time.time())).limit(1)):
        raise SystemExit('Wait for the AI queue to be idle before this diagnostic')
    adapter = OllamaProvider(get_settings())
    guard = DeviceGuard(adapter, 'qwen4', 'gpu')
    error = ''
    result = {}
    try:
        with guard.execution():
            guard.receipt['inference_started'] = True
            result = adapter.propose_context(evidence, context, 'qwen4')
    except InferenceError as exc:
        error = str(exc)
    actual = {(p['metric'], p['number_text']) for p in result.get('proposals', [])}
    matched = actual == expected and len(result.get('proposals', [])) == len(expected)
    print(json.dumps(dict(scope='Synthetic engineering probe, not real gold or 95% accuracy',
        expected=sorted(expected), observed=sorted(actual), all_numbers_matched=matched,
        error=error, result=result, execution=guard.receipt)), flush=True)
    if error or not matched:
        raise SystemExit(1)

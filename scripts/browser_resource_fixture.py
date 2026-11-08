"""Opt-in synthetic waiting task; low-memory condition is explicitly simulated."""
import io
import json
import sys
import time
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.api import create_app
from goldenstock.auth import Actor
from goldenstock.ai_runs import enqueue,proposal_source
from goldenstock.models import AIRun,AIExecution,User

credentials=json.load(sys.stdin);app=create_app()
buffer=io.BytesIO();pdf=canvas.Canvas(buffer)
pdf.drawString(50,750,'Synthetic CPU test. Total assets USD 120 million in 2025.');pdf.save()
with TestClient(app) as client:
    client.headers['origin']=app.state.settings.public_url
    auth=client.post('/api/v1/auth/login',json=credentials);auth.raise_for_status()
    client.headers['x-csrf-token']=auth.json()['csrf']
    response=client.post('/api/v1/documents',data={'company_id':'jpm'},
        headers={'Idempotency-Key':'browser-resource-test'},
        files={'file':('synthetic-resource.pdf',buffer.getvalue())})
    response.raise_for_status();source=response.json()
    for _ in range(45):
        job=client.get('/api/v1/jobs/'+source['job_id']).json()
        if job['state']=='succeeded': break
        time.sleep(1)
    client.post('/api/v1/jobs/'+source['job_id']+'/extract').raise_for_status()
    for _ in range(45):
        if client.get('/api/v1/jobs/'+source['job_id']+'/extraction').status_code==200: break
        time.sleep(1)
    with Session(app.state.engine) as db,db.begin():
        user=db.scalar(select(User).where(User.login==credentials['login']))
        actor=Actor(user.id,user.org_id,user.login,user.account_admin,'')
        payload=proposal_source(db,actor,source['job_id'],0,0)
        result=enqueue(db,actor,payload.pop('company_id'),'proposals','qwen_small',payload)
        row=db.get(AIRun,result['id']);row.state='awaiting_device';row.error='gpu_reserve_unavailable';row.attempts=1
        now=time.time()
        db.add(AIExecution(run_id=row.id,attempt=1,state='awaiting_device',started=now,finished=now,
            receipt=json.dumps(dict(policy='synthetic-browser-fixture',simulated=True,
                requested_device='gpu',observed_device=None,free_before_mib=2048,seconds=0,
                inference_started=False,cleanup_confirmed=True))))
        key=row.id
    print(json.dumps(dict(run_id=key)))
app.state.engine.dispose()

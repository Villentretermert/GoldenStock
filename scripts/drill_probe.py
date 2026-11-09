"""Probe the recovered application over certificate-validated HTTPS from a peer container."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
import ssl
import sys
import threading
import time
import httpx

receipt = json.load(sys.stdin)
origin = "https://recovered-web:8443"
tls = ssl.create_default_context(cafile="/drill-ca.pem")
barrier = threading.Barrier(15, timeout=30)


def client():
    return httpx.Client(base_url=origin, verify=tls, trust_env=False, timeout=30, headers={"Origin":origin})


def analyst(i):
    session = client()
    barrier.wait()
    start = time.monotonic()
    login = session.post("/api/v1/auth/login", json={"login":f"drill{i}", "password":os.environ["GS_QA_PASSWORD"]})
    login.raise_for_status()
    cookie = login.headers["set-cookie"].lower()
    assert all(flag in cookie for flag in ("secure","httponly","samesite=strict"))
    session.headers["x-csrf-token"] = login.json()["csrf"]
    assert session.get("/api/v1/auth/me").json()["login"] == f"drill{i}"
    session.get("/api/v1/companies").raise_for_status()
    return session, (time.monotonic() - start) * 1000


with client() as anonymous:
    for attempt in range(40):
        try:
            if anonymous.get("/health/ready").status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("Recovered app did not become ready")
    assert anonymous.get("/api/v1/companies").status_code == 401
    anonymous.cookies.set("gs_session", receipt["old_session"])
    assert anonymous.get("/api/v1/auth/me").status_code == 401

with ThreadPoolExecutor(max_workers=15) as pool:
    sessions = list(pool.map(analyst, range(15)))
try:
    admin = sessions[0][0]
    original = receipt["document"]
    path = f'/api/v1/documents/{original["document_id"]}/versions/{original["version_id"]}/download'
    assert hashlib.sha256(admin.get(path).content).hexdigest() == original["sha256"]
    assert sessions[1][0].get(path).status_code == 404
    template = receipt["template"]
    path = f'/api/v1/templates/{template["template_id"]}/versions/{template["id"]}/original'
    assert hashlib.sha256(admin.get(path).content).hexdigest() == receipt["template_sha"]
    assert admin.get('/api/v1/template-updates').json()['items']==[receipt['template_update']]
    for peer,_ in sessions[1:]:
        update=peer.get('/api/v1/template-updates').json()['items']
        assert len(update)==1 and update[0]['publication_id']==receipt['template_update']['publication_id']
        assert update[0]['read_at'] is None and update[0]['detail']==receipt['template_update']['detail']
        assert peer.get(path).status_code==404
    assert sessions[1][0].post('/api/v1/template-updates/'+receipt['template_update']['id']+'/read').status_code==404
    private_update=sessions[1][0].get('/api/v1/template-updates').json()['items'][0]
    sessions[1][0].post('/api/v1/template-updates/'+private_update['id']+'/read').raise_for_status()
    knowledge = admin.get("/api/v1/knowledge/jpm/export").json()
    mapped=receipt['workbook_map'];mapped_url='/api/v1/workbook-maps/'+mapped['id']
    assert admin.get(mapped_url).json()==mapped
    assert hashlib.sha256(admin.get(mapped_url+'/original').content).hexdigest()==receipt['workbook_sha']
    assert sessions[1][0].get(mapped_url).status_code==404 and sessions[1][0].get(mapped_url+'/original').status_code==404
    assert len(knowledge["facts"]) == 1 and knowledge["state_hash"] == receipt["knowledge_hash"]
    labels=receipt['lab_exchange'];import_url='/api/v1/lab/exchange/imports/'+labels['import_id']
    restored_labels=admin.get(import_url).json()
    assert restored_labels['dataset_id']==labels['dataset_id'] and restored_labels['confirmation_note']==labels['confirmation']['reason']
    assert hashlib.sha256(admin.get(import_url+'/original').content).hexdigest()==labels['original_sha']
    assert sessions[1][0].get(import_url).status_code==404 and sessions[1][0].get(import_url+'/original').status_code==404
    assert admin.post(import_url+'/confirm',json=labels['confirmation']).json()['fingerprint']==labels['fingerprint']
    assert admin.get(receipt['monitor_history_url']).json()==receipt['monitor_history']
    assert admin.get('/api/v1/notifications?category=revisions').json()['items']==[receipt['monitor_update']]
    assert sessions[1][0].get('/api/v1/notifications').json()['items']==[]
    assert sessions[1][0].post('/api/v1/notifications/'+receipt['monitor_update']['id']+'/read').status_code==404
    batch_url='/api/v1/ai/batches/'+receipt['batch_id']
    restored_batch=admin.get(batch_url);restored_batch.raise_for_status()
    assert restored_batch.json()['manifest']==receipt['batch_manifest']
    assert restored_batch.json()['manifest']['with_context'] is True
    assert sessions[1][0].get(batch_url).status_code==404
    saved_run=restored_batch.json()['runs'][0]['run_id']
    assert admin.get('/api/v1/ai/runs/'+saved_run).json()['executions']==receipt['batch_executions']
    assert admin.post(batch_url+'/retry').status_code==200
    for _ in range(35):
        restored_batch=admin.get(batch_url).json()
        if restored_batch['state']=='awaiting_device': break
        time.sleep(1)
    assert restored_batch['counts']=={'awaiting_device':1}
    run_id=restored_batch['runs'][0]['run_id']
    waiting=admin.get('/api/v1/ai/runs/'+run_id).json()
    assert waiting['executions'][-1]['requested_device']=='gpu'
    assert waiting['executions'][-1]['inference_started'] is False
    # Clean CPU-only stand: analyst choice is required even when no GPU exists.
    assert admin.post(batch_url+'/use-cpu').status_code==200
    for _ in range(35):
        restored_batch=admin.get(batch_url).json()
        if restored_batch['completed']==restored_batch['total']: break
        time.sleep(1)
    assert restored_batch['counts']=={'failed':1}  # No inference service in the restore drill.
    attempts=admin.get('/api/v1/ai/runs/'+run_id).json()['executions']
    assert attempts[-2]==waiting['executions'][-1]
    assert attempts[-1]['requested_device']=='cpu'
    pending=receipt['pending_document']
    pending_url='/api/v1/jobs/'+pending['job_id']
    assert admin.get(pending_url).json()['progress']==dict(status='partial',completed_pages=25,total_pages=26)
    assert admin.get(pending_url+'/extraction').status_code==409
    assert sessions[1][0].get(pending_url).status_code==404
    admin.post(pending_url+'/retry').raise_for_status()
    for _ in range(40):
        status=admin.get(pending_url).json()
        if status['state']=='succeeded': break
        if status['state']=='failed': raise RuntimeError('Restored prefix could not resume: '+status['error_code'])
        time.sleep(1)
    result=admin.get(pending_url+'/extraction'); result.raise_for_status()
    assert result.json()['source_sha256']==pending['sha256']
    assert [i['location']['page'] for i in result.json()['items']]==list(range(1,27))
    assert admin.put("/api/v1/favorites/jpm", headers={"Origin":"https://untrusted.invalid"}).status_code == 403
    employee = sessions[-1][0].get("/api/v1/auth/me").json()["id"]
    admin.patch("/api/v1/users/"+employee, json={"active":False}).raise_for_status()
    assert sessions[-1][0].get("/api/v1/companies").status_code == 401
    run = admin.post("/api/v1/ai/proposals", json={"job_id": original["job_id"]})
    run.raise_for_status()
    run_url='/api/v1/ai/runs/'+run.json()['id']
    for _ in range(35):
        if admin.get(run_url).json()['state']=='awaiting_device': break
        time.sleep(1)
    assert admin.post(run_url+'/use-cpu').status_code==200
    for attempt in range(35):
        result = admin.get("/api/v1/ai/runs/"+run.json()["id"]).json()
        if result["state"] == "failed":
            break
        time.sleep(1)
    else:
        raise RuntimeError("Disconnected provider did not fail its queued task")
    admin.get("/api/v1/companies").raise_for_status()
    admin.get("/health/ready").raise_for_status()
    timings = sorted(item[1] for item in sessions)
    print(json.dumps(dict(concurrent_accounts=len(sessions), scenario="HTTPS login, session and catalog",
                          p50_ms=round(timings[7]), p95_ms=round(timings[math.ceil(.95*15)-1]),
                          original=True, template=True, workbook_map_restored=True, template_publications_restored=True, reviewed_knowledge=True, lab_exchange_restored=True, sec_history_restored=True, ai_batch_restored=True, ai_execution_history_restored=True, explicit_cpu=True, pdf_checkpoint_resumed=True, revoked_session_denied=True,
                          old_session_denied=True, inference_outage_isolated=True)))
finally:
    for session, _ in sessions:
        session.close()

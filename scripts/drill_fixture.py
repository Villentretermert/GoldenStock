"""Synthetic source data for the isolated GS-023 rehearsal. Executed inside its web container."""
import hashlib
import json
import os
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.api import create_app
from goldenstock.auth import hash_password
from goldenstock.models import Extraction, Organization, User, ExtractionCheckpoint, Job

app = create_app()
password = os.environ["GS_QA_PASSWORD"]
with Session(app.state.engine) as db, db.begin():
    if db.scalar(select(User.id).limit(1)):
        raise RuntimeError("Fixture needs a fresh test database")
    org = Organization(name="Synthetic recovery fund")
    db.add(org)
    db.flush()
    hashed = hash_password(password)
    for i in range(15):
        db.add(User(org_id=org.id, login=f"drill{i}", password_hash=hashed, account_admin=i == 0))

with TestClient(app) as client:
    client.headers["origin"] = app.state.settings.public_url
    auth = client.post("/api/v1/auth/login", json=dict(login="drill0", password=password))
    auth.raise_for_status()
    client.headers["x-csrf-token"] = auth.json()["csrf"]
    pdf = b"%PDF-1.4\nSynthetic recovery evidence: 2 USD millions.\n%%EOF"
    upload = client.post("/api/v1/documents", data=dict(company_id="jpm"),
                         headers={"Idempotency-Key":"gs023-private-document"},
                         files={"file":("recovery.pdf", pdf, "application/pdf")})
    upload.raise_for_status()
    original = upload.json()
    with Session(app.state.engine) as db, db.begin():
        db.add(Extraction(version_id=original["version_id"], parser_version="drill",
                          source_sha256=original["sha256"], payload=json.dumps({"items":[
                              dict(text="2", location={"page":1}, method="native")]})))
    fact = client.post("/api/v1/facts", json=dict(job_id=original["job_id"], item_index=0,
        metric="profit", number_text="2", unit="money", scale="millions", currency="USD", period_kind="year",
        period_start="2025-01-01", period_end="2025-12-31", scope="group", scope_detail="Synthetic group",
        accounting="IFRS", definition="Total profit after tax", disclosure="original"))
    fact.raise_for_status()
    client.post("/api/v1/facts/"+fact.json()["id"]+"/reviews",json=dict(
        decision="accepted", expected_revision=0, note="Synthetic recovery reference")).raise_for_status()
    demo = client.get("/api/v1/templates/demo")
    demo.raise_for_status()
    template = client.post("/api/v1/templates", data={"title":"Recovery reference"},
                           headers={"Idempotency-Key":"gs023-private-template"},
                           files={"file":("reference.xlsx",demo.content)})
    template.raise_for_status()
    knowledge = client.get("/api/v1/knowledge/jpm/export").json()
    assert len(knowledge["facts"]) == 1
    batch_args=dict(job_id=original['job_id'],page_start=1,page_end=1,profile='qwen4',with_context=True)
    planned=client.get('/api/v1/ai/batches/preview',params=batch_args);planned.raise_for_status()
    batch=client.post('/api/v1/ai/batches',json=batch_args|dict(plan_hash=planned.json()['plan_hash']))
    batch.raise_for_status();batch_id=batch.json()['id']
    stopped=client.post('/api/v1/ai/batches/'+batch_id+'/cancel')
    assert stopped.status_code in (200,409)
    batch_manifest=client.get('/api/v1/ai/batches/'+batch_id).json()['manifest']
    # A cancelled long-PDF prefix must survive backup and resume on the clean server.
    import io
    from reportlab.pdfgen import canvas
    from goldenstock import jobs
    from goldenstock.extraction import PDF_PARSER_VERSION
    buffer=io.BytesIO(); document=canvas.Canvas(buffer)
    for number in range(1,27):
        document.drawString(50,750,f'Synthetic recovery page {number}'); document.showPage()
    document.save()
    pending=client.post('/api/v1/documents',data=dict(company_id='jpm'),
        headers={'Idempotency-Key':'gs025-recovery-prefix'},
        files={'file':('pending.pdf',buffer.getvalue(),'application/pdf')})
    pending.raise_for_status(); pending=pending.json()
    from goldenstock.extraction import extract_pdf_chunk
    from goldenstock.storage import FileStore
    from goldenstock.models import DocumentVersion
    with Session(app.state.engine) as db,db.begin():
        version=db.get(DocumentVersion,pending['version_id'])
        prefix=extract_pdf_chunk(FileStore(app.state.settings.data_dir).path(version.blob_key),1,25)
        encoded=json.dumps(prefix)
        job=db.get(Job,pending['job_id']); job.kind='extract_document'; job.state='cancelled'
        db.add(ExtractionCheckpoint(version_id=version.id,parser_version=PDF_PARSER_VERSION,
            source_sha256=version.sha256,completed_pages=25,total_pages=26,payload=encoded,
            payload_sha256=hashlib.sha256(encoded.encode()).hexdigest()))
    print(json.dumps(dict(document=original, template=template.json(), knowledge_hash=knowledge["state_hash"],
                          pending_document=pending,batch_id=batch_id,batch_manifest=batch_manifest,
                          template_sha=hashlib.sha256(demo.content).hexdigest(),
                          old_session=client.cookies.get("gs_session"))))

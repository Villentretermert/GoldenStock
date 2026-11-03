"""Create a private synthetic cancelled PDF for the opt-in browser check."""
import hashlib
import io
import json
import sys
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session
from goldenstock.api import create_app
from goldenstock.extraction import extract_pdf_chunk, PDF_PARSER_VERSION
from goldenstock.models import DocumentVersion, ExtractionCheckpoint, Job
from goldenstock.storage import FileStore

credentials=json.load(sys.stdin)
app=create_app()
buffer=io.BytesIO(); pdf=canvas.Canvas(buffer)
for number in range(1,27):
    pdf.drawString(50,750,f'Synthetic browser page {number}'); pdf.showPage()
pdf.save()
with TestClient(app) as client:
    client.headers['origin']=app.state.settings.public_url
    auth=client.post('/api/v1/auth/login',json=credentials); auth.raise_for_status()
    client.headers['x-csrf-token']=auth.json()['csrf']
    response=client.post('/api/v1/documents',data={'company_id':'jpm'},
        headers={'Idempotency-Key':'browser-pdf-prefix'},files={'file':('synthetic-pdf-progress.pdf',buffer.getvalue())})
    response.raise_for_status(); receipt=response.json()
    with Session(app.state.engine) as db,db.begin():
        job=db.get(Job,receipt['job_id']); job.state='cancelled'; job.kind='extract_document'
        version=db.get(DocumentVersion,receipt['version_id'])
        prefix=extract_pdf_chunk(FileStore(app.state.settings.data_dir).path(version.blob_key),1,25)
        encoded=json.dumps(prefix)
        db.add(ExtractionCheckpoint(version_id=version.id,parser_version=PDF_PARSER_VERSION,
            source_sha256=version.sha256,completed_pages=25,total_pages=26,payload=encoded,
            payload_sha256=hashlib.sha256(encoded.encode()).hexdigest()))
app.state.engine.dispose()

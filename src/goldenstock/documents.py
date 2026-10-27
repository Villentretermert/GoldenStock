"""Authorized originals, immutable versions, and scoped idempotent upload receipts."""
import hashlib
import json
import re
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile
from goldenstock.auth import authenticate, visible, owned, audit
from goldenstock.models import Company, Document, DocumentVersion, Job, JobEvent, Extraction, new_id
from goldenstock.storage import FileStore, validate_file

router = APIRouter(prefix='/api/v1')


def receipt(db, version):
    job = db.scalar(select(Job).where(Job.version_id == version.id))
    return {'document_id':version.document_id,'version_id':version.id,'number':version.number,
            'sha256':version.sha256,'job_id':job.id,'state':job.state,'kind':job.kind}


@router.post('/documents',status_code=201)
async def upload(request: Request):
    actor = authenticate(request,True)
    key = request.headers.get('idempotency-key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',key):
        raise HTTPException(422,'Idempotency-Key must contain 8–100 letters, digits, underscores or hyphens')
    async with request.form(max_files=1,max_fields=3,max_part_size=1024) as form:
        file = form.get('file')
        if not isinstance(file,UploadFile):
            raise HTTPException(422,'One file is required')
        company_id = str(form.get('company_id',''))
        document_id = str(form.get('document_id',''))
        content = await file.read(request.app.state.settings.max_file_bytes+1)
        filename = file.filename
        validate_file(filename,content,request.app.state.settings.max_file_bytes)
    sha = hashlib.sha256(content).hexdigest()
    fingerprint = hashlib.sha256(json.dumps([sha,filename,company_id,document_id]).encode()).hexdigest()
    store = FileStore(request.app.state.settings.data_dir)
    blob = None
    try:
        with Session(request.app.state.engine) as db, db.begin():
            if not db.get(Company,company_id):
                raise HTTPException(404,'Company not found')
            old = db.scalar(select(DocumentVersion).where(DocumentVersion.owner_id==actor.id,DocumentVersion.idem_key==key))
            if old:
                if old.request_hash != fingerprint:
                    raise HTTPException(409,'Idempotency key already used with different input')
                owned(db,Document,old.document_id,actor)
                return receipt(db,old)
            if document_id:
                document = owned(db,Document,document_id,actor,True)
                if document.company_id != company_id:
                    raise HTTPException(409,'A version must belong to the same company')
                expected = document.revision
                changed = db.execute(update(Document).where(Document.id==document.id,Document.revision==expected).values(revision=expected+1))
                if not changed.rowcount:
                    raise HTTPException(409,'Concurrent version upload; retry')
                number = expected+1
            else:
                document = Document(org_id=actor.org_id,owner_id=actor.id,company_id=company_id,filename=filename)
                db.add(document); db.flush()
                number = 1
            version_id = new_id()
            blob = f'{actor.org_id}/{actor.id}/{version_id}'
            store.write(blob,content)
            version = DocumentVersion(id=version_id,document_id=document.id,org_id=actor.org_id,owner_id=actor.id,
                number=number,filename=filename,sha256=sha,size=len(content),blob_key=blob,idem_key=key,request_hash=fingerprint)
            db.add(version); db.flush()
            job = Job(org_id=actor.org_id,actor_id=actor.id,version_id=version.id)
            db.add(job); db.flush()
            db.add(JobEvent(job_id=job.id,state='queued',attempt=0))
            audit(db,actor,'document.upload',version.id,f'sha256={sha};version={number}')
            result = receipt(db,version)
        return result
    except Exception as exc:
        if blob:
            store.path(blob).unlink(missing_ok=True)
        if isinstance(exc,IntegrityError):
            # A concurrent identical key may already have committed successfully.
            with Session(request.app.state.engine) as db:
                old = db.scalar(select(DocumentVersion).where(DocumentVersion.owner_id==actor.id,DocumentVersion.idem_key==key))
                if old and old.request_hash==fingerprint:
                    return receipt(db,old)
            raise HTTPException(409,'Concurrent upload conflict; refresh and retry') from None
        raise


@router.get('/documents')
def documents(request: Request, q: str = '', company_id: str = ''):
    actor = authenticate(request)
    with Session(request.app.state.engine) as db:
        stmt = select(Document).where(visible(Document,actor),Document.filename.icontains(q[:200],autoescape=True))
        if company_id:
            stmt = stmt.where(Document.company_id==company_id)
        result=[]
        for doc in db.scalars(stmt.limit(200)):
            versions=[]
            for version in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==doc.id).order_by(DocumentVersion.number.desc())):
                item=receipt(db,version)
                item.update(filename=version.filename,size=version.size,created=version.created)
                versions.append(item)
            result.append(dict(id=doc.id,filename=doc.filename,company_id=doc.company_id,versions=versions))
        return result


@router.get('/documents/{document_id}/versions/{version_id}/download')
def download(document_id: str, version_id: str, request: Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        owned(db,Document,document_id,actor)
        version=db.scalar(select(DocumentVersion).where(DocumentVersion.id==version_id,DocumentVersion.document_id==document_id,DocumentVersion.org_id==actor.org_id))
        if not version:
            raise HTTPException(404,'Version not found')
        path=FileStore(request.app.state.settings.data_dir).path(version.blob_key)
        if not path.is_file():
            raise HTTPException(409,'Original is unavailable; contact the operator')
        return FileResponse(path,filename=version.filename,media_type='application/octet-stream',
                            headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


def authorized_job(db,job_id,actor):
    job=db.scalar(select(Job).where(Job.id==job_id,Job.org_id==actor.org_id))
    version=db.get(DocumentVersion,job.version_id) if job else None
    if not version:
        raise HTTPException(404,'Job not found')
    owned(db,Document,version.document_id,actor)
    return job


@router.get('/jobs/{job_id}')
def job_status(job_id: str,request: Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        job=authorized_job(db,job_id,actor)
        history=[dict(state=event.state,attempt=event.attempt,created=event.created) for event in db.scalars(
            select(JobEvent).where(JobEvent.job_id==job.id).order_by(JobEvent.created))]
        return dict(id=job.id,state=job.state,attempts=job.attempts,error_code=job.error_code,history=history,kind=job.kind)


@router.post('/jobs/{job_id}/extract')
def extract_job(job_id: str, request: Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        job=authorized_job(db,job_id,actor)
        if job.kind=='extract_document':
            return {'ok':True}  # Duplicate clicks do not create duplicate evidence.
        changed=db.execute(update(Job).where(Job.id==job.id,Job.kind=='verify_original',
            Job.state=='succeeded').values(kind='extract_document',state='queued',attempts=0,
                available_at=0,error_code='',lease_token='',lease_until=0))
        if not changed.rowcount:
            raise HTTPException(409,'Verify the original before extraction')
        db.add(JobEvent(job_id=job.id,state='extraction_queued',attempt=0))
        audit(db,actor,'document.extract',job.version_id)
    return {'ok':True}


@router.get('/jobs/{job_id}/extraction')
def extraction_result(job_id: str, request: Request, offset: int = 0, limit: int = 100):
    actor=authenticate(request)
    if offset<0 or not 1<=limit<=200:
        raise HTTPException(422,'Invalid page bounds')
    with Session(request.app.state.engine) as db:
        job=authorized_job(db,job_id,actor)
        result=db.get(Extraction,job.version_id)
        if not result:
            raise HTTPException(409,'Extraction is not available')
        payload=json.loads(result.payload)
        items=payload.pop('items')
        version=db.get(DocumentVersion,job.version_id)
        return dict(payload,version_id=result.version_id,source_sha256=result.source_sha256,
            document_id=version.document_id,filename=version.filename,version_number=version.number,
            total=len(items),offset=offset,items=items[offset:offset+limit])


@router.post('/jobs/{job_id}/retry')
def retry_job(job_id: str,request: Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        job=authorized_job(db,job_id,actor)
        if job.actor_id!=actor.id:
            raise HTTPException(404,'Job not found')
        changed=db.execute(update(Job).where(Job.id==job.id,Job.state=='failed').values(state='queued',attempts=0,available_at=0,error_code=''))
        if not changed.rowcount:
            raise HTTPException(409,'Only failed jobs can be retried')
        db.add(JobEvent(job_id=job.id,state='manual_retry',attempt=0))
        audit(db,actor,'job.retry',job.id)
    return {'ok':True}

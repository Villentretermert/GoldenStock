"""At-least-once queue; lease tokens fence stale workers from committing results."""
import time
import json
import hashlib
from pathlib import Path
from sqlalchemy import select, update, delete, or_, and_
from sqlalchemy.orm import Session
from goldenstock.models import Job, JobEvent, User, Document, DocumentVersion, Extraction, ExtractionCheckpoint, WorkerHeartbeat, new_id
from goldenstock.storage import FileStore
from goldenstock.extraction import ExtractionError, PDF_PARSER_VERSION
from goldenstock.parser_process import run_parser, validate_pdf_payload

MAX_ATTEMPTS=3
LEASE_SECONDS=60


def claim(engine,now=None):
    now=time.time() if now is None else now
    with Session(engine) as db,db.begin():
        eligible=or_(and_(Job.state.in_(['queued','retry']),Job.available_at<=now),and_(Job.state=='running',Job.lease_until<=now))
        job=db.scalar(select(Job).where(eligible).order_by(Job.created).with_for_update(skip_locked=True).limit(1))
        if not job:
            return None
        if job.attempts>=MAX_ATTEMPTS:
            db.execute(update(Job).where(Job.id==job.id,eligible).values(state='failed',error_code='attempts_exhausted'))
            db.add(JobEvent(job_id=job.id,state='failed',attempt=job.attempts))
            return None
        token=new_id()
        attempts=job.attempts+1
        changed=db.execute(update(Job).where(Job.id==job.id,eligible).values(state='running',attempts=attempts,lease_token=token,lease_until=now+LEASE_SECONDS))
        if not changed.rowcount:
            return None
        db.add(JobEvent(job_id=job.id,state='running',attempt=attempts))
        return job.id,token


def permitted(db,job,lock_actor=False):
    if not job:
        return None
    actor=(db.scalar(select(User).where(User.id==job.actor_id).with_for_update())
           if lock_actor else db.get(User,job.actor_id))
    version=db.get(DocumentVersion,job.version_id)
    doc=db.get(Document,version.document_id) if version else None
    if not actor or not actor.active or not doc or not version:
        return None
    if actor.org_id!=job.org_id or doc.org_id!=job.org_id or version.org_id!=job.org_id or doc.owner_id!=actor.id:
        return None
    return version


def renew(engine, settings, job_id, token):
    with Session(engine) as db, db.begin():
        job = db.get(Job, job_id)
        if not permitted(db, job):
            return False
        changed = db.execute(update(Job).where(Job.id==job_id, Job.lease_token==token,
            Job.state=='running', Job.lease_until>time.time()).values(lease_until=time.time()+LEASE_SECONDS))
        if changed.rowcount:
            db.merge(WorkerHeartbeat(worker_id=settings.worker_id, last_seen=time.time()))
        return bool(changed.rowcount)


def save_pdf_checkpoint(engine, job_id, token, source_sha256, payload):
    end, total = validate_pdf_payload(payload)
    encoded = json.dumps(payload, ensure_ascii=True)
    with Session(engine) as db, db.begin():
        # Same row lock as cancellation/final commit: an old worker cannot overwrite progress.
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        version = permitted(db, job, lock_actor=True)
        if (not version or job.state != 'running' or job.lease_token != token or
                job.lease_until <= time.time() or version.sha256 != source_sha256):
            raise ExtractionError('lease_or_access_lost')
        db.merge(ExtractionCheckpoint(version_id=version.id, parser_version=PDF_PARSER_VERSION,
            source_sha256=source_sha256, completed_pages=end, total_pages=total, payload=encoded,
            payload_sha256=hashlib.sha256(encoded.encode()).hexdigest()))
        db.add(JobEvent(job_id=job_id, state='pdf_checkpoint', attempt=job.attempts))


def load_pdf_checkpoint(db, version):
    row = db.get(ExtractionCheckpoint, version.id)
    if row is None:
        return None
    if (row.parser_version != PDF_PARSER_VERSION or row.source_sha256 != version.sha256 or
            hashlib.sha256(row.payload.encode()).hexdigest() != row.payload_sha256):
        raise ExtractionError('invalid_pdf_checkpoint')
    try:
        payload = json.loads(row.payload)
    except ValueError:
        raise ExtractionError('invalid_pdf_checkpoint') from None
    if validate_pdf_payload(payload) != (row.completed_pages, row.total_pages):
        raise ExtractionError('invalid_pdf_checkpoint')
    return payload


def execute(engine,settings,claim_result,now=None):
    if not claim_result:
        return
    clock_now=(lambda: time.time()) if now is None else (lambda: now)
    available_at=clock_now()
    job_id,token=claim_result
    code=''
    payload=None
    checkpoint=None
    with Session(engine) as db:
        job=db.get(Job,job_id)
        if not job or job.state!='running' or job.lease_token!=token or job.lease_until<=clock_now():
            return
        version=permitted(db,job)
        if not version:
            code='access_revoked'
        else:
            try:
                if FileStore(settings.data_dir).checksum(version.blob_key)!=version.sha256:
                    code='checksum_mismatch'
            except OSError:
                code='storage_unavailable'
        kind=job.kind
        if version:
            path=FileStore(settings.data_dir).path(version.blob_key)
            extension=Path(version.filename).suffix.lower()
            version_id,source_sha256=version.id,version.sha256
        if not code and kind=='extract_document' and extension=='.pdf':
            try:
                checkpoint=load_pdf_checkpoint(db,version)
            except ExtractionError as exc:
                code=str(exc)
    # No long-lived DB transaction while CPU/OCR work runs in the child process.
    if not code and kind=='extract_document':
        try:
            options = dict(checkpoint=checkpoint, save_checkpoint=lambda data:
                save_pdf_checkpoint(engine,job_id,token,source_sha256,data)) if extension=='.pdf' else {}
            payload=run_parser(path,extension,lambda: renew(engine,settings,job_id,token),**options)
            if FileStore(settings.data_dir).checksum(version.blob_key)!=source_sha256:
                code='checksum_mismatch'
        except ExtractionError as exc:
            code=str(exc)
        except OSError:
            code='storage_unavailable'
    with Session(engine) as db,db.begin():
        job=db.scalar(select(Job).where(Job.id==job_id).with_for_update())
        if not job or job.state!='running' or job.lease_token!=token or job.lease_until<=clock_now():
            return
        if not permitted(db,job,lock_actor=True):
            code='access_revoked'
        state='succeeded' if not code else ('retry' if code=='storage_unavailable' and job.attempts<MAX_ATTEMPTS else 'failed')
        changed=db.execute(update(Job).where(Job.id==job_id,Job.lease_token==token,Job.state=='running',Job.lease_until>clock_now()).values(
            state=state,error_code=code,available_at=available_at+min(60,2**job.attempts),lease_until=0))
        if changed.rowcount:
            if payload is not None and not code:
                db.merge(Extraction(version_id=version_id, parser_version=payload['parser_version'],
                    source_sha256=source_sha256, payload=json.dumps(payload,ensure_ascii=True)))
                db.execute(delete(ExtractionCheckpoint).where(ExtractionCheckpoint.version_id==version_id))
            db.add(JobEvent(job_id=job.id,state=state,attempt=job.attempts))


def process_one(engine,settings):
    execute(engine,settings,claim(engine))

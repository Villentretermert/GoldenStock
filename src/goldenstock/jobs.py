"""At-least-once queue; lease tokens fence stale workers from committing results."""
import time
import json
from pathlib import Path
from sqlalchemy import select, update, or_, and_
from sqlalchemy.orm import Session
from goldenstock.models import Job, JobEvent, User, Document, DocumentVersion, Extraction, WorkerHeartbeat, new_id
from goldenstock.storage import FileStore
from goldenstock.extraction import ExtractionError
from goldenstock.parser_process import run_parser

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


def permitted(db,job):
    if not job:
        return None
    actor=db.get(User,job.actor_id)
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


def execute(engine,settings,claim_result,now=None):
    if not claim_result:
        return
    now=time.time() if now is None else now
    job_id,token=claim_result
    code=''
    payload=None
    with Session(engine) as db:
        job=db.get(Job,job_id)
        if not job or job.state!='running' or job.lease_token!=token:
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
        if not code and job.kind == 'extract_document':
            try:
                payload=run_parser(FileStore(settings.data_dir).path(version.blob_key),
                    Path(version.filename).suffix.lower(), lambda: renew(engine,settings,job_id,token))
            except ExtractionError as exc:
                code=str(exc)
    with Session(engine) as db,db.begin():
        job=db.get(Job,job_id)
        if not permitted(db,job):
            code='access_revoked'
        state='succeeded' if not code else ('retry' if code=='storage_unavailable' and job.attempts<MAX_ATTEMPTS else 'failed')
        changed=db.execute(update(Job).where(Job.id==job_id,Job.lease_token==token,Job.state=='running').values(
            state=state,error_code=code,available_at=now+min(60,2**job.attempts),lease_until=0))
        if changed.rowcount:
            if payload is not None and not code:
                db.merge(Extraction(version_id=version.id, parser_version=payload['parser_version'],
                    source_sha256=version.sha256, payload=json.dumps(payload,ensure_ascii=True)))
            db.add(JobEvent(job_id=job.id,state=state,attempt=job.attempts))


def process_one(engine,settings):
    execute(engine,settings,claim(engine))

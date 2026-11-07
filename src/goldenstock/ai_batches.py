"""Atomic page selection and private progress over the existing serial AI queue."""
import hashlib
import json
import time
from collections import Counter
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from goldenstock.ai_evidence import source_window
from goldenstock.auth import authenticate, audit
from goldenstock.documents import authorized_job
from goldenstock.inference import PROFILES, inference_spec, InferenceError
from goldenstock.models import AIProposalBatch, AIRun, Company, Document, DocumentVersion, Extraction

router=APIRouter(prefix='/api/v1/ai/batches')
POLICY='gs029-pdf-batch-v1'
MAX_WINDOWS=10
MAX_PAGES=25


def owned(db,cls,key,actor,write=False):
    query=select(cls).where(cls.id==key,cls.org_id==actor.org_id,cls.owner_id==actor.id)
    row=db.scalar(query.with_for_update() if write else query)
    if not row: raise HTTPException(404,'Private object not found')
    return row


def encode(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=True)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def page_windows(payload,version_id,source_hash,page_start,page_end):
    items=payload['items']
    total=payload.get('coverage',{}).get('total_pages') or max(
        (i.get('location',{}).get('page',0) for i in items),default=0)
    if not 1 <= page_start <= page_end <= total or page_end-page_start+1>MAX_PAGES:
        raise ValueError('Choose 1–25 original PDF pages within this document')
    indices=[n for n,i in enumerate(items) if page_start<=i.get('location',{}).get('page',0)<=page_end]
    windows=[]; segments=[]
    for index in indices:
        if not segments or segments[-1][1]!=index:
            segments.append([index,index+1])
        else: segments[-1][1]+=1
    for first,stop in segments:
        cursor=dict(offset=first,text_offset=0)
        while cursor:
            part=source_window(items,version_id,source_hash,**cursor,stop_offset=stop)
            cursor=part['next_cursor']
            if part['evidence']:
                windows.append(part)
                if len(windows)>MAX_WINDOWS:
                    raise ValueError('Selected pages need more than 10 AI requests; choose a smaller page range. Nothing was queued.')
    covered={e['location']['page'] for w in windows for e in w['evidence']}
    return dict(windows=windows,total_pages=total,
                empty_pages=[p for p in range(page_start,page_end+1) if p not in covered])


def selection(db,actor,job_id,page_start,page_end,profile):
    if profile not in PROFILES: raise HTTPException(422,'Unknown local profile')
    job=authorized_job(db,job_id,actor)
    version=owned(db,DocumentVersion,job.version_id,actor)
    if not version.filename.lower().endswith('.pdf'): raise HTTPException(422,'Page batches require a PDF original')
    extracted=db.get(Extraction,version.id)
    if not extracted: raise HTTPException(409,'Extract the complete original first')
    try: plan=page_windows(json.loads(extracted.payload),version.id,extracted.source_sha256,page_start,page_end)
    except ValueError as exc: raise HTTPException(422,str(exc)) from None
    plan.update(policy=POLICY,job_id=job.id,version_id=version.id,filename=version.filename,
        company_id=db.get(Document,version.document_id).company_id,source_sha256=extracted.source_sha256,
        parser_version=extracted.parser_version,page_start=page_start,page_end=page_end,
        spec=inference_spec('proposals',profile))
    return plan


@router.get('/preview')
def preview(request:Request,job_id:str,page_start:int=Query(1,ge=1,le=1000),
            page_end:int=Query(1,ge=1,le=1000),profile:str='qwen4'):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        plan=selection(db,actor,job_id,page_start,page_end,profile)
        return dict(plan,plan_hash=digest(plan))


class BatchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    job_id:str=Field(max_length=32)
    page_start:int=Field(ge=1,le=1000)
    page_end:int=Field(ge=1,le=1000)
    profile:str='qwen4'
    plan_hash:str=Field(pattern=r'^[0-9a-f]{64}$')


def lock(db):
    db.scalar(select(Company).where(Company.id=='sber').with_for_update())


def pending(db,actor):
    return db.scalar(select(func.count()).select_from(AIRun).where(
        AIRun.org_id==actor.org_id,AIRun.owner_id==actor.id,AIRun.state.in_(['queued','running'])))


@router.post('',status_code=201)
def create(data:BatchRequest,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        lock(db)
        plan=selection(db,actor,data.job_id,data.page_start,data.page_end,data.profile)
        fingerprint=digest(plan)
        if fingerprint!=data.plan_hash: raise HTTPException(409,'Preview changed; refresh before starting the batch')
        old=db.scalar(select(AIProposalBatch).where(AIProposalBatch.org_id==actor.org_id,
            AIProposalBatch.owner_id==actor.id,AIProposalBatch.fingerprint==fingerprint))
        if old: return dict(id=old.id)
        if not plan['windows']: raise HTTPException(422,'No extracted text on selected pages')
        if pending(db,actor)+len(plan['windows'])>10:
            raise HTTPException(429,'Batch does not fit the ten-task queue. Wait or choose fewer pages; nothing was queued.')
        row=AIProposalBatch(org_id=actor.org_id,owner_id=actor.id,company_id=plan['company_id'],
            version_id=plan['version_id'],fingerprint=fingerprint,manifest='',manifest_hash='')
        db.add(row);db.flush();entries=[]
        for index,window in enumerate(plan['windows']):
            frozen=dict(window,batch_id=row.id,batch_spec=plan['spec'],batch_policy=POLICY,
                        job_id=plan['job_id'],version_id=plan['version_id'])
            run=AIRun(org_id=actor.org_id,owner_id=actor.id,company_id=row.company_id,
                kind='batch_proposals',profile=data.profile,input=encode(frozen),
                fingerprint=digest(dict(batch=row.id,position=index,input=frozen)))
            db.add(run);db.flush()
            entries.append(dict(run_id=run.id,input_hash=digest(frozen),position=index,
                pages=sorted({e['location']['page'] for e in window['evidence']})))
        manifest={k:v for k,v in plan.items() if k!='windows'}
        manifest['entries']=entries
        row.manifest=encode(manifest);row.manifest_hash=digest(manifest)
        audit(db,actor,'ai.batch.created',row.id,fingerprint)
        return dict(id=row.id)


def checked(db,row,actor):
    manifest=json.loads(row.manifest)
    if digest(manifest)!=row.manifest_hash: raise HTTPException(409,'Batch manifest checksum mismatch')
    pairs=[]
    for entry in manifest['entries']:
        run=owned(db,AIRun,entry['run_id'],actor)
        frozen=json.loads(run.input)
        if (run.kind!='batch_proposals' or run.company_id!=row.company_id or
            run.profile!=manifest['spec']['profile'] or frozen.get('batch_id')!=row.id or
            digest(frozen)!=entry['input_hash']):
            raise HTTPException(409,'Batch input checksum mismatch')
        pairs.append((entry,run))
    return manifest,pairs


@router.get('')
def listing(request:Request,company_id:str):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        return [dict(id=r.id,created=r.created) for r in db.scalars(select(AIProposalBatch).where(
            AIProposalBatch.org_id==actor.org_id,AIProposalBatch.owner_id==actor.id,
            AIProposalBatch.company_id==company_id).order_by(AIProposalBatch.created.desc()).limit(30))]


@router.get('/{key}')
def detail(key:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=owned(db,AIProposalBatch,key,actor);manifest,pairs=checked(db,row,actor)
        counts=Counter(r.state for _,r in pairs)
        state=('running' if counts['running'] else 'queued') if counts['queued']+counts['running'] else (
            'succeeded' if counts['succeeded']==len(pairs) else 'finished_with_gaps')
        return dict(id=row.id,company_id=row.company_id,created=row.created,manifest=manifest,
            state=state,total=len(pairs),completed=sum(counts[s] for s in ('succeeded','failed','cancelled')),
            counts=dict(counts),runs=[dict(entry,state=r.state,error=r.error,attempts=r.attempts,
                proposal_count=len(json.loads(r.output).get('proposals',[]))) for entry,r in pairs])


@router.post('/{key}/{action}')
def control(key:str,action:str,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        lock(db);row=owned(db,AIProposalBatch,key,actor,True);_,pairs=checked(db,row,actor)
        if action=='cancel':
            targets=[r for _,r in pairs if r.state in {'queued','running'}]
            if not targets: raise HTTPException(409,'No pending parts to cancel')
            for r in targets: r.state='cancelled'  # Preserve leases until running calls return.
        elif action=='retry':
            targets=[r for _,r in pairs if r.state in {'failed','cancelled'}]
            if not targets: raise HTTPException(409,'No failed or cancelled parts to retry')
            if any(r.lease_until>time.time() for r in targets): raise HTTPException(409,'Wait for the running call to release its lease')
            if pending(db,actor)+len(targets)>10: raise HTTPException(429,'Retry does not fit the ten-task queue')
            for r in targets: r.state='queued';r.error='';r.output='{}';r.lease_token=''
        else: raise HTTPException(422,'Unknown batch action')
        audit(db,actor,'ai.batch.'+action,row.id)
        return dict(id=row.id)


def validate_batch_input(payload,profile,engine,actor,run_id):
    if payload.get('batch_policy')!=POLICY or payload.get('batch_spec')!=inference_spec('proposals',profile):
        raise InferenceError('batch_configuration_changed')
    try:
        with Session(engine) as db:
            row=owned(db,AIProposalBatch,payload['batch_id'],actor)
            _,pairs=checked(db,row,actor)
            if not any(r.id==run_id and digest(payload)==entry['input_hash'] for entry,r in pairs):
                raise HTTPException(409,'Batch input mismatch')
    except (HTTPException,KeyError,ValueError):
        raise InferenceError('batch_input_changed') from None

"""Server-owned task dispatch; model output has no execution privileges."""
import hashlib
import json
import secrets
import time
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate,audit,Actor
from goldenstock.models import AIRun,Company,DocumentVersion,Document,Extraction,User
from goldenstock.documents import authorized_job
from goldenstock.inference import PROFILES,PROMPT_VERSION,OllamaProvider,InferenceError
from goldenstock.knowledge import pack,retrieve
from goldenstock.public_sources import snapshot as public_snapshot,evidence as public_evidence

router=APIRouter(prefix='/api/v1/ai')


def private(actor):
    return (AIRun.org_id==actor.org_id)&(AIRun.owner_id==actor.id)


def view(row):
    return dict(id=row.id,company_id=row.company_id,kind=row.kind,profile=row.profile,state=row.state,
        error=row.error,attempts=row.attempts,created=row.created,result=json.loads(row.output))


class ProposalRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    job_id: str=Field(max_length=32)
    offset: int=Field(default=0,ge=0,le=49999)
    profile: str='qwen4'


class SummaryRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    company_id:str=Field(max_length=32)
    profile:str='qwen4'


@router.post('/public-summaries',status_code=201)
def public_summary(data:SummaryRequest,request:Request):
    actor=authenticate(request,True)
    if data.profile not in PROFILES: raise HTTPException(422,'Unknown local profile')
    with Session(request.app.state.engine) as db,db.begin():
        row=public_snapshot(db,data.company_id,request.app.state.settings)
        selected=public_evidence(row)
        if not selected: raise HTTPException(409,'No supported recent public metrics; coverage gap retained')
        payload=dict(evidence=selected,snapshot_id=row.id,as_of=max(e['period_end'] for e in selected),retrieved_at=row.created)
        return enqueue(db,actor,data.company_id,'public_summary',data.profile,payload)


@router.post('/summaries',status_code=201)
def summaries(data:SummaryRequest,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        data_pack=pack(db,actor,data.company_id)
        found=retrieve(data_pack,'profit equity assets roe roa nim cost income npl risk mau ltv',limit=4)
        if not found['evidence']: raise HTTPException(409,'No confirmed facts. Upload and review English source documents first.')
        found['as_of']=max(f['period_end'] for f in data_pack['facts'])
        return enqueue(db,actor,data.company_id,'summary',data.profile,found)


def enqueue(db,actor,company_id,kind,profile,payload):
    if profile not in PROFILES: raise HTTPException(422,'Unknown local profile')
    encoded=json.dumps(payload,sort_keys=True)
    fingerprint=hashlib.sha256((kind+profile+PROFILES[profile].digest+PROMPT_VERSION+'summary-v3-extractive'+encoded).encode()).hexdigest()
    # One shared scheduling lock; SQLite is only a development/test backend.
    db.scalar(select(Company).where(Company.id=='sber').with_for_update())
    old=db.scalar(select(AIRun).where(private(actor),AIRun.fingerprint==fingerprint))
    if old: return view(old)
    count=db.scalar(select(func.count()).select_from(AIRun).where(private(actor),AIRun.state.in_(['queued','running'])))
    if count>=10: raise HTTPException(429,'Maximum ten pending AI tasks per analyst')
    row=AIRun(org_id=actor.org_id,owner_id=actor.id,company_id=company_id,kind=kind,profile=profile,input=encoded,fingerprint=fingerprint)
    db.add(row);db.flush();audit(db,actor,'ai.queued',row.id,kind)
    return view(row)


@router.get('/profiles')
def profiles(request:Request):
    authenticate(request)
    return [dict(id=k,model=v.model,context=v.context,output_tokens=v.output_tokens) for k,v in PROFILES.items()]


@router.post('/proposals',status_code=201)
def proposals(data:ProposalRequest,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        job=authorized_job(db,data.job_id,actor)
        version=db.get(DocumentVersion,job.version_id)
        if version.owner_id!=actor.id: raise HTTPException(404,'Private original not found')
        extraction=db.get(Extraction,version.id)
        if not extraction: raise HTTPException(409,'Extract the original first')
        items=json.loads(extraction.payload)['items'];evidence=[];used=0
        for index,item in enumerate(items[data.offset:data.offset+8],start=data.offset):
            text=item.get('text') or ''
            if not text.strip(): continue
            entry=dict(id=f'{version.id}:{index}',text=text,location=item['location'],source_sha256=extraction.source_sha256)
            size=len(json.dumps(entry))
            if used+size>6000: break
            evidence.append(entry);used+=size
        if not evidence: raise HTTPException(422,'No bounded evidence at this offset; choose a smaller source item')
        company=db.get(Document,version.document_id).company_id
        return enqueue(db,actor,company,'proposals',data.profile,dict(evidence=evidence,version_id=version.id,job_id=job.id,offset=data.offset))


@router.get('/runs')
def runs(request:Request,company_id:str):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        return [view(r) for r in db.scalars(select(AIRun).where(private(actor),AIRun.company_id==company_id).order_by(AIRun.created.desc()).limit(50))]


@router.get('/runs/{run_id}')
def run(run_id:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=db.scalar(select(AIRun).where(private(actor),AIRun.id==run_id))
        if not row: raise HTTPException(404,'Run not found')
        result=view(row)
        if row.kind=='summary':
            payload=json.loads(row.input)
            result['current']=pack(db,actor,row.company_id)['state_hash']==payload['state_hash']
            result['as_of']=payload['as_of'];result['blocker_count']=payload['blocker_count']
        elif row.kind=='public_summary':
            payload=json.loads(row.input)
            result.update(as_of=payload['as_of'],retrieved_at=payload['retrieved_at'],snapshot_id=payload['snapshot_id'])
        return result


@router.post('/runs/{run_id}/{action}')
def control(run_id:str,action:str,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        db.scalar(select(Company).where(Company.id=='sber').with_for_update())
        row=db.scalar(select(AIRun).where(private(actor),AIRun.id==run_id).with_for_update())
        if not row: raise HTTPException(404,'Run not found')
        if action=='cancel' and row.state in {'queued','running'}:
            row.state='cancelled' # Keep the lease until the provider returns; no overlapping GPU work.
        elif action=='retry' and row.state in {'failed','cancelled'} and row.lease_until<=time.time():
            row.state='queued';row.error='';row.lease_token=''
        else: raise HTTPException(409,'Action unavailable for this run')
        audit(db,actor,'ai.'+action,row.id)
        return view(row)


def process_ai(engine,settings,provider=None):
    now=time.time()
    with Session(engine) as db,db.begin():
        db.scalar(select(Company).where(Company.id=='sber').with_for_update())
        if db.scalar(select(AIRun.id).where(AIRun.lease_until>now).limit(1)): return False
        for stale in db.scalars(select(AIRun).where(AIRun.state=='running',AIRun.lease_until<=now)):
            stale.state='failed';stale.error='worker_interrupted';stale.lease_token=''
        row=db.scalar(select(AIRun).where(AIRun.state=='queued').order_by(AIRun.created).limit(1).with_for_update())
        if not row: return False
        user=db.get(User,row.owner_id)
        if not user or not user.active or user.org_id!=row.org_id:
            row.state='failed';row.error='access_revoked';return True
        row.state='running';row.attempts+=1;row.lease_token=secrets.token_hex(16);row.lease_until=now+240
        key,token,profile,payload,kind=row.id,row.lease_token,row.profile,json.loads(row.input),row.kind
        actor=Actor(user.id,user.org_id,user.login,user.account_admin,'')
        audit(db,actor,'ai.running',key)
    output={};error=''
    try:
        adapter=provider or OllamaProvider(settings)
        output=adapter.summarize(payload['evidence'],profile) if kind in {'summary','public_summary'} else adapter.propose(payload['evidence'],profile)
    except InferenceError as exc: error=str(exc)
    except Exception: error='inference_failed'
    with Session(engine) as db,db.begin():
        row=db.scalar(select(AIRun).where(AIRun.id==key).with_for_update())
        user=db.get(User,row.owner_id)
        if row.lease_token!=token: return True
        row.lease_until=0
        if row.state!='running': return True
        if not user or not user.active or user.org_id!=row.org_id: error='access_revoked'
        if time.time()>now+240: error='lease_expired'
        row.state='failed' if error else 'succeeded';row.error=error
        row.output=json.dumps(output if not error else {})
        audit(db,actor,'ai.'+row.state,key,error)
    return True

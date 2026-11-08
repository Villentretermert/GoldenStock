"""Private immutable datasets and experiments; labels never enter inference inputs."""
import json
import secrets
import time
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate,audit
from goldenstock.models import (LabDataset,LabExperiment,LabAnnotation,LabSourceSplit,
    AIRun,Company,Document,DocumentVersion,Extraction)
from goldenstock.documents import authorized_job
from goldenstock.inference import PROFILES,inference_spec,InferenceError
from goldenstock.knowledge import pack,retrieve
from goldenstock.lab_scoring import encode,digest,validate_reference,counts,aggregate,POLICY
from goldenstock.ai_resources import PENDING,choose_device,history as device_history

router=APIRouter(prefix='/api/v1/lab')


def owned(db,model,key,actor,lock=False):
    query=select(model).where(model.id==key,model.org_id==actor.org_id,model.owner_id==actor.id)
    row=db.scalar(query.with_for_update() if lock else query)
    if not row: raise HTTPException(404,'Private lab object not found')
    return row


def scheduling_lock(db):
    # Same lock as production AI work: one GPU queue, including multiple workers.
    db.scalar(select(Company).where(Company.id=='sber').with_for_update())


class CaseRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    job_id:str | None=Field(default=None,max_length=32)
    company_id:str | None=Field(default=None,max_length=32)
    offset:int=Field(default=0,ge=0,le=49999)
    expected:list=Field(max_length=12)


class DatasetRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=160)
    kind:Literal['proposals','summary']
    split:Literal['development','holdout']
    parent_id:str | None=Field(default=None,max_length=32)
    cases:list[CaseRequest]=Field(min_length=1,max_length=4)
    reference_confirmed:Literal[True]


class ExperimentRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset_id:str=Field(max_length=32)
    profiles:list[str]=Field(default=['qwen4','qwen_small'],min_length=2,max_length=2)


class AnnotationRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=0)
    verdict:Literal['correct','incorrect','uncertain']
    reason:str=Field(min_length=5,max_length=1000)


def prepare_case(db,actor,kind,data):
    if kind=='summary':
        if not data.company_id or data.job_id: raise HTTPException(422,'Select a company for citation selection')
        evidence=retrieve(pack(db,actor,data.company_id),'profit equity assets roe roa nim cost income npl risk mau ltv',limit=4)['evidence']
        company_id=data.company_id
    else:
        if not data.job_id or data.company_id: raise HTTPException(422,'Select an extracted document for metrics')
        job=authorized_job(db,data.job_id,actor)
        version=db.get(DocumentVersion,job.version_id)
        if version.owner_id!=actor.id: raise HTTPException(404,'Private original not found')
        extraction=db.get(Extraction,version.id)
        if not extraction: raise HTTPException(409,'Extract the source first')
        evidence=[];used=0
        for index,item in enumerate(json.loads(extraction.payload)['items'][data.offset:data.offset+8],start=data.offset):
            if not (item.get('text') or '').strip(): continue
            entry=dict(id=f'{version.id}:{index}',text=item['text'],location=item['location'],source_sha256=extraction.source_sha256)
            size=len(json.dumps(entry))
            if used+size>6000: break
            evidence.append(entry);used+=size
        company_id=db.get(Document,version.document_id).company_id
    if not evidence or len(json.dumps(evidence))>7000: raise HTTPException(422,'No bounded evidence; choose a different offset or review facts')
    return dict(company_id=company_id,evidence=evidence,input_hash=digest(evidence),
        source=dict(job_id=data.job_id,company_id=data.company_id,offset=data.offset))


@router.post('/preview')
def preview(data:DatasetRequest,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db:
        return dict(cases=[prepare_case(db,actor,data.kind,case) for case in data.cases])


def dataset_view(row,full=False):
    value=dict(id=row.id,title=row.title,revision=row.revision,parent_id=row.parent_id,
        kind=row.kind,split=row.split,fingerprint=row.fingerprint,created=row.created)
    if full: value['snapshot']=checked_dataset(row)
    return value


def checked_dataset(row):
    payload=json.loads(row.payload)
    if digest(payload)!=row.fingerprint: raise HTTPException(409,'Dataset checksum mismatch')
    if payload.get('policy')!=POLICY: raise HTTPException(409,'Dataset policy version unavailable')
    return payload


@router.post('/datasets',status_code=201)
def create_dataset(data:DatasetRequest,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        scheduling_lock(db)
        parent=owned(db,LabDataset,data.parent_id,actor) if data.parent_id else None
        if parent and (parent.split!=data.split or parent.kind!=data.kind): raise HTTPException(409,'A revision must preserve task and split')
        cases=[];seen=set();sources=set()
        for item in data.cases:
            case=prepare_case(db,actor,data.kind,item)
            identity=digest([{k:e[k] for k in ('source_sha256','text','location')} for e in case['evidence']])
            if identity in seen: raise HTTPException(422,'Duplicate case input')
            seen.add(identity)
            try: case['expected']=validate_reference(data.kind,item.expected,case['evidence'])
            except (ValueError,TypeError,KeyError,ArithmeticError): raise HTTPException(422,'Invalid reference labels: use source IDs, verbatim quotes and reported numbers') from None
            cases.append(case)
            sources.update(e['source_sha256'] for e in case['evidence'])
        payload=dict(policy=POLICY,kind=data.kind,split=data.split,cases=cases)
        fingerprint=digest(payload)
        previous=db.scalar(select(LabDataset).where(LabDataset.owner_id==actor.id,LabDataset.fingerprint==fingerprint))
        if previous: return dataset_view(previous,True)
        for source in sources:
            registered=db.get(LabSourceSplit,(actor.id,source))
            if registered and registered.split!=data.split: raise HTTPException(409,'This source document already belongs to the other split')
            if not registered: db.add(LabSourceSplit(owner_id=actor.id,source_hash=source,split=data.split))
        # A reference change after an experiment consumed holdout is not a fresh holdout.
        if data.split=='holdout':
            for old in db.scalars(select(LabDataset).where(LabDataset.owner_id==actor.id,LabDataset.split=='holdout')):
                overlap=sources & {e['source_sha256'] for c in checked_dataset(old)['cases'] for e in c['evidence']}
                if overlap and db.scalar(select(LabExperiment.id).where(LabExperiment.dataset_id==old.id).limit(1)):
                    raise HTTPException(409,'Consumed holdout sources cannot be relabelled or repackaged; use new source documents')
        row=LabDataset(org_id=actor.org_id,owner_id=actor.id,title=data.title.strip(),kind=data.kind,split=data.split,
            parent_id=parent.id if parent else None,revision=parent.revision+1 if parent else 1,
            fingerprint=fingerprint,payload=encode(payload))
        if not row.title: raise HTTPException(422,'Title required')
        db.add(row);db.flush();audit(db,actor,'lab.dataset.created',row.id,fingerprint)
        return dataset_view(row,True)


@router.get('/datasets')
def datasets(request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        return [dataset_view(r) for r in db.scalars(select(LabDataset).where(LabDataset.org_id==actor.org_id,LabDataset.owner_id==actor.id).order_by(LabDataset.created.desc()).limit(100))]


@router.get('/datasets/{key}')
def dataset(key:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db: return dataset_view(owned(db,LabDataset,key,actor),True)


@router.post('/experiments',status_code=201)
def create_experiment(data:ExperimentRequest,request:Request):
    actor=authenticate(request,True)
    if len(set(data.profiles))!=2 or any(p not in PROFILES for p in data.profiles): raise HTTPException(422,'Choose two different installed profiles')
    with Session(request.app.state.engine) as db,db.begin():
        scheduling_lock(db)
        source=owned(db,LabDataset,data.dataset_id,actor);payload=checked_dataset(source)
        specs=[inference_spec(source.kind,p) for p in sorted(data.profiles)]
        fingerprint=digest(dict(dataset=source.fingerprint,specs=specs,policy=POLICY))
        old=db.scalar(select(LabExperiment).where(LabExperiment.owner_id==actor.id,LabExperiment.fingerprint==fingerprint))
        if old: return dict(id=old.id)
        if source.split=='holdout' and db.scalar(select(LabExperiment.id).where(LabExperiment.dataset_id==source.id).limit(1)):
            raise HTTPException(409,'Holdout already consumed; create a fresh independent dataset for new configurations')
        pending=db.scalar(select(func.count()).select_from(AIRun).where(AIRun.owner_id==actor.id,AIRun.state.in_(PENDING)))
        if pending+2*len(payload['cases'])>10: raise HTTPException(429,'Maximum ten pending AI tasks per analyst')
        row=LabExperiment(org_id=actor.org_id,owner_id=actor.id,dataset_id=source.id,fingerprint=fingerprint,manifest='',manifest_hash='')
        db.add(row);db.flush()
        secrets.SystemRandom().shuffle(specs)
        entries=[]
        for variant,spec in enumerate(specs,start=1):
            for index,case in enumerate(payload['cases']):
                # Labels are deliberately absent from AIRun input.
                frozen=dict(evidence=case['evidence'],lab_spec=spec,lab_kind=source.kind,lab_experiment=row.id,lab_input_hash=case['input_hash'])
                run=AIRun(org_id=actor.org_id,owner_id=actor.id,company_id=case['company_id'],kind='lab_'+source.kind,
                    profile=spec['profile'],input=encode(frozen),fingerprint=digest(dict(experiment=row.id,case=index,spec=spec)))
                db.add(run);db.flush()
                entries.append(dict(run_id=run.id,variant=f'Variant {variant}',case=index,spec=spec,input_hash=case['input_hash']))
        manifest=dict(policy=POLICY,dataset_hash=source.fingerprint,entries=entries)
        row.manifest=encode(manifest);row.manifest_hash=digest(manifest)
        audit(db,actor,'lab.experiment.created',row.id,source.fingerprint)
        return dict(id=row.id)


def checked_manifest(db,row,actor):
    manifest=json.loads(row.manifest)
    source=owned(db,LabDataset,row.dataset_id,actor)
    payload=checked_dataset(source)
    if digest(manifest)!=row.manifest_hash or manifest['dataset_hash']!=source.fingerprint: raise HTTPException(409,'Experiment checksum mismatch')
    if manifest.get('policy')!=POLICY: raise HTTPException(409,'Scoring policy version unavailable')
    pairs=[]
    for entry in manifest['entries']:
        run=owned(db,AIRun,entry['run_id'],actor)
        frozen=json.loads(run.input);case=payload['cases'][entry['case']]
        if (frozen.get('lab_spec')!=entry['spec'] or run.profile!=entry['spec']['profile'] or
            run.kind!='lab_'+source.kind or frozen.get('lab_experiment')!=row.id or
            digest(frozen['evidence'])!=entry['input_hash'] or entry['input_hash']!=case['input_hash']):
            raise HTTPException(409,'Run input checksum mismatch')
        pairs.append((entry,run))
    return source,payload,pairs


def annotations(db,row,run):
    return list(db.scalars(select(LabAnnotation).where(LabAnnotation.experiment_id==row.id,LabAnnotation.run_id==run.id).order_by(LabAnnotation.revision)))


def annotation_view(a):
    return dict(revision=a.revision,verdict=a.verdict,reason=a.reason,output_hash=a.output_hash,created=a.created)


def experiment_view(db,row,actor):
    source,payload,pairs=checked_manifest(db,row,actor)
    output=dict(id=row.id,dataset=dataset_view(source),revealed=row.revealed,created=row.created,
        manifest_hash=row.manifest_hash if row.revealed else None,runs=[],comparison=[],quality_target_confirmed=False)
    grouped={}
    for entry,run in pairs:
        result=json.loads(run.output);history=annotations(db,row,run)
        item=dict(id=run.id,variant=entry['variant'],case=entry['case'],state=run.state,
            error=run.error,annotations=[annotation_view(a) for a in history],output={})
        if run.state=='succeeded':
            # No provider/model/timing fields in the blind review API or HTML.
            item['output']={k:result[k] for k in ('proposals','claims','gaps') if k in result}
        if row.revealed:
            item.update(spec=entry['spec'],receipt=result,executions=device_history(db,run))
            group=grouped.setdefault(entry['variant'],dict(profile=entry['spec']['profile'],rows=[],seconds=[],tokens=[],succeeded=0,failed=0,human_correct=0))
            case=payload['cases'][entry['case']]
            if run.state=='succeeded':
                group['succeeded']+=1
                group['rows'].append(counts(source.kind,case['expected'],result,case['evidence']))
                if isinstance(result.get('seconds'),(int,float)): group['seconds'].append(result['seconds'])
                if isinstance(result.get('tokens'),int): group['tokens'].append(result['tokens'])
                group['human_correct']+=int(bool(history) and history[-1].verdict=='correct')
            else:
                group['failed']+=1
                # Failures/abstentions count as missed references, never vanish from recall.
                group['rows'].append(counts(source.kind,case['expected'],{},case['evidence']))
        output['runs'].append(item)
    for variant,g in grouped.items():
        output['comparison'].append(dict(variant=variant,profile=g['profile'],metrics=aggregate(g['rows']),
            succeeded=g['succeeded'],failed=g['failed'],human_correct=g['human_correct'],
            seconds=sum(g['seconds']) if len(g['seconds'])==g['succeeded'] and g['succeeded'] else None,
            tokens=sum(g['tokens']) if len(g['tokens'])==g['succeeded'] and g['succeeded'] else None,
            monetary_cost=None))
    return output


@router.get('/experiments')
def experiments(request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        return [dict(id=r.id,dataset_id=r.dataset_id,revealed=r.revealed,created=r.created) for r in db.scalars(select(LabExperiment).where(LabExperiment.org_id==actor.org_id,LabExperiment.owner_id==actor.id).order_by(LabExperiment.created.desc()).limit(100))]


@router.get('/experiments/{key}')
def experiment(key:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db: return experiment_view(db,owned(db,LabExperiment,key,actor),actor)


@router.post('/experiments/{key}/runs/{run_id}/annotations',status_code=201)
def annotate(key:str,run_id:str,data:AnnotationRequest,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        row=owned(db,LabExperiment,key,actor,True)
        _,_,pairs=checked_manifest(db,row,actor)
        run=next((r for _,r in pairs if r.id==run_id),None)
        if not run: raise HTTPException(404,'Run not found')
        if row.revealed or run.state!='succeeded': raise HTTPException(409,'Only successful unrevealed results can be annotated')
        history=annotations(db,row,run)
        if data.revision!=(history[-1].revision if history else 0): raise HTTPException(409,'Annotation changed; reload')
        if len(data.reason.strip())<5: raise HTTPException(422,'Explain your judgement')
        annotation=LabAnnotation(experiment_id=row.id,run_id=run.id,actor_id=actor.id,revision=data.revision+1,
            verdict=data.verdict,reason=data.reason.strip(),output_hash=digest(json.loads(run.output)))
        db.add(annotation);db.flush();audit(db,actor,'lab.annotation.created',annotation.id)
        return annotation_view(annotation)


@router.post('/experiments/{key}/{action}')
def control(key:str,action:str,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        scheduling_lock(db)
        row=owned(db,LabExperiment,key,actor,True)
        _,_,pairs=checked_manifest(db,row,actor)
        if row.revealed: raise HTTPException(409,'Revealed experiments are immutable')
        if action=='reveal':
            for _,run in pairs:
                if run.state in PENDING or run.lease_until>time.time(): raise HTTPException(409,'Wait for all variants to finish')
                if run.state=='succeeded':
                    history=annotations(db,row,run)
                    if not history or history[-1].output_hash!=digest(json.loads(run.output)): raise HTTPException(409,'Review every successful answer before revealing models')
            row.revealed=True
        elif action in {'use-cpu','check-gpu'}:
            choose_device([r for _,r in pairs],action)
        elif action=='cancel':
            for _,run in pairs:
                if run.state in PENDING: run.state='cancelled'
        elif action=='retry':
            retry=[r for _,r in pairs if r.state in {'failed','cancelled'}]
            if not retry or any(r.lease_until>time.time() for r in retry): raise HTTPException(409,'Retry unavailable while a provider call is still active')
            pending=db.scalar(select(func.count()).select_from(AIRun).where(AIRun.owner_id==actor.id,AIRun.state.in_(PENDING)))
            if pending+len(retry)>10: raise HTTPException(429,'Maximum ten pending AI tasks per analyst')
            for run in retry: run.state='queued';run.error='';run.lease_token=''
        else: raise HTTPException(404,'Unknown experiment action')
        audit(db,actor,'lab.experiment.'+action,row.id)
        return dict(id=row.id,revealed=row.revealed)


def validate_lab_input(payload,profile):
    if (payload.get('lab_spec')!=inference_spec(payload['lab_kind'],profile) or
        digest(payload['evidence'])!=payload.get('lab_input_hash')):
        raise InferenceError('experiment_version_changed')

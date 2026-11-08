"""Private annotation workbooks: frozen draft, checked preview, explicit reference save."""
import hashlib
import json
import time
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import Response
from starlette.datastructures import UploadFile
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate,audit
from goldenstock.models import LabDataset,LabExchange,LabImport
from goldenstock.ai_lab import (CaseRequest,owned,scheduling_lock,prepare_case,checked_dataset,
    check_split,save_dataset,dataset_view)
from goldenstock.lab_scoring import encode,digest
from goldenstock.lab_workbook import FORMAT,MAX_BYTES,export_workbook,parse_book,labels_from_book

router=APIRouter(prefix='/api/v1/lab/exchange')
MIME='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class DraftRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=160)
    kind:Literal['proposals','summary']
    split:Literal['development','holdout']
    cases:list[CaseRequest]=Field(min_length=1,max_length=4)


class ConfirmRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    candidate_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    reference_confirmed:Literal[True]
    reason:str=Field(min_length=5,max_length=1000)


def checked(row):
    payload=json.loads(row.payload)
    if digest(payload)!=row.fingerprint or payload.get('format')!=FORMAT:
        raise HTTPException(409,'Workbook draft checksum or format mismatch')
    return payload


def live_check(db,actor,payload):
    parent=owned(db,LabDataset,payload['parent_id'],actor) if payload['parent_id'] else None
    if parent:
        if (parent.fingerprint!=payload['parent_hash'] or parent.revision!=payload['parent_revision'] or
            parent.kind!=payload['kind'] or parent.split!=payload['split']):
            raise HTTPException(409,'Reference version changed')
        checked_dataset(parent)
        if db.scalar(select(LabDataset.id).where(LabDataset.parent_id==parent.id).limit(1)):
            raise HTTPException(409,'Reference has a newer revision; export the latest version')
    check_split(db,actor,payload['split'],payload['cases'])
    for case in payload['cases']:
        current=prepare_case(db,actor,payload['kind'],CaseRequest(**case['source'],expected=[]))
        if current['input_hash']!=case['input_hash'] or current['company_id']!=case['company_id']:
            raise HTTPException(409,'Source evidence changed; export a fresh workbook')
    return parent


def save_draft(db,actor,title,kind,split,cases,parent=None):
    payload=dict(format=FORMAT,title=title.strip(),kind=kind,split=split,cases=cases,
        parent_id=parent.id if parent else None,parent_hash=parent.fingerprint if parent else None,
        parent_revision=parent.revision if parent else None)
    if not payload['title']: raise HTTPException(422,'Title required')
    live_check(db,actor,payload)
    # Reserve the source split at draft creation, before any labels are accepted.
    check_split(db,actor,split,cases,register=True)
    fingerprint=digest(payload)
    previous=db.scalar(select(LabExchange).where(LabExchange.owner_id==actor.id,LabExchange.fingerprint==fingerprint))
    if previous: return previous
    row=LabExchange(org_id=actor.org_id,owner_id=actor.id,fingerprint=fingerprint,payload=encode(payload))
    db.add(row);db.flush();audit(db,actor,'lab.exchange.created',row.id,fingerprint)
    return row


@router.post('/drafts',status_code=201)
def draft(data:DraftRequest,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        scheduling_lock(db);cases=[];seen=set()
        for source in data.cases:
            if source.expected: raise HTTPException(422,'Drafts start unlabelled; export a saved dataset to revise labels')
            case=prepare_case(db,actor,data.kind,source)
            identity=digest([{k:e[k] for k in ('source_sha256','text','location')} for e in case['evidence']])
            if identity in seen: raise HTTPException(422,'Duplicate source case')
            seen.add(identity);cases.append(dict(case,expected=[]))
        row=save_draft(db,actor,data.title,data.kind,data.split,cases)
        return dict(id=row.id)


@router.post('/datasets/{key}',status_code=201)
def from_dataset(key:str,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        scheduling_lock(db);parent=owned(db,LabDataset,key,actor);payload=checked_dataset(parent)
        row=save_draft(db,actor,parent.title,parent.kind,parent.split,payload['cases'],parent)
        return dict(id=row.id)


@router.get('/drafts')
def drafts(request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        return [dict(id=r.id,title=checked(r)['title'],created=r.created) for r in db.scalars(select(LabExchange).where(
            LabExchange.org_id==actor.org_id,LabExchange.owner_id==actor.id).order_by(LabExchange.created.desc()).limit(100))]


@router.get('/drafts/{key}')
def draft_detail(key:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=owned(db,LabExchange,key,actor);payload=checked(row)
        imports=list(db.scalars(select(LabImport).where(LabImport.exchange_id==row.id).order_by(LabImport.created.desc())))
        return dict(id=row.id,manifest_sha256=row.fingerprint,**payload,
            imports=[dict(id=r.id,created=r.created,dataset_id=r.dataset_id) for r in imports])


@router.get('/drafts/{key}/download')
def download(key:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=owned(db,LabExchange,key,actor);payload=checked(row)
        return Response(export_workbook(row,payload),media_type=MIME,
            headers={'Content-Disposition':f'attachment; filename="goldenstock-annotation-{row.id[:8]}.xlsx"'})


@router.post('/imports',status_code=201)
async def import_preview(request:Request):
    actor=authenticate(request,True)
    async with request.form(max_files=1,max_fields=0,max_part_size=1024) as data:
        upload=data.get('file')
        if not isinstance(upload,UploadFile) or not (upload.filename or '').lower().endswith('.xlsx'):
            raise HTTPException(422,'Upload the completed annotation XLSX')
        content=await upload.read(MAX_BYTES+1)
    parsed=parse_book(content)
    meta=dict(parsed['Guide'])
    key=meta.get('exchange_id','')
    with Session(request.app.state.engine) as db,db.begin():
        scheduling_lock(db);row=owned(db,LabExchange,key,actor);payload=checked(row)
        sha=hashlib.sha256(content).hexdigest()
        previous=db.scalar(select(LabImport).where(LabImport.exchange_id==row.id,LabImport.sha256==sha))
        if previous:
            if not previous.dataset_id: live_check(db,actor,payload)
            return dict(id=previous.id)
        live_check(db,actor,payload)
        cases=labels_from_book(parsed,row,payload)
        candidate=dict(exchange_id=row.id,manifest_sha256=row.fingerprint,kind=payload['kind'],split=payload['split'],cases=cases)
        imported=LabImport(org_id=actor.org_id,owner_id=actor.id,exchange_id=row.id,sha256=sha,original=content,
            candidate=encode(candidate),candidate_hash=digest(candidate))
        db.add(imported);db.flush();audit(db,actor,'lab.import.previewed',imported.id,sha)
        return dict(id=imported.id)


def checked_import(row,exchange):
    candidate=json.loads(row.candidate)
    if (digest(candidate)!=row.candidate_hash or candidate.get('exchange_id')!=exchange.id or
        candidate.get('manifest_sha256')!=exchange.fingerprint or hashlib.sha256(row.original).hexdigest()!=row.sha256):
        raise HTTPException(409,'Import receipt checksum mismatch')
    return candidate


@router.get('/imports/{key}')
def import_detail(key:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=owned(db,LabImport,key,actor);exchange=owned(db,LabExchange,row.exchange_id,actor)
        payload=checked(exchange);candidate=checked_import(row,exchange)
        conflict=None
        if not row.dataset_id:
            try: live_check(db,actor,payload)
            except HTTPException as exc: conflict=exc.detail
        return dict(id=row.id,exchange_id=exchange.id,title=payload['title'],kind=payload['kind'],split=payload['split'],
            candidate_hash=row.candidate_hash,source_sha256=row.sha256,dataset_id=row.dataset_id,
            confirmation_note=row.confirmation_note,confirmed_at=row.confirmed_at,conflict=conflict,
            changes=[dict(case=f'C{i+1}',before=old['expected'],after=new['expected'],evidence=new['evidence'])
                for i,(old,new) in enumerate(zip(payload['cases'],candidate['cases']))])


@router.get('/imports/{key}/original')
def original(key:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=owned(db,LabImport,key,actor);exchange=owned(db,LabExchange,row.exchange_id,actor);checked_import(row,exchange)
        return Response(row.original,media_type=MIME,headers={'Content-Disposition':'attachment; filename="imported-annotation.xlsx"'})


@router.post('/imports/{key}/confirm')
def confirm(key:str,data:ConfirmRequest,request:Request):
    actor=authenticate(request,True)
    if len(data.reason.strip())<5: raise HTTPException(422,'Explain the reference review')
    with Session(request.app.state.engine) as db,db.begin():
        scheduling_lock(db);row=owned(db,LabImport,key,actor,True);exchange=owned(db,LabExchange,row.exchange_id,actor)
        payload=checked(exchange);candidate=checked_import(row,exchange)
        if data.candidate_hash!=row.candidate_hash: raise HTTPException(409,'Preview changed; reload before confirming')
        if row.dataset_id: return dataset_view(owned(db,LabDataset,row.dataset_id,actor),True)
        parent=live_check(db,actor,payload)
        # Re-parse the retained original so preview storage cannot bypass field validation.
        cases=labels_from_book(parse_book(row.original),exchange,payload)
        if cases!=candidate['cases']: raise HTTPException(409,'Candidate differs from original workbook')
        result=save_dataset(db,actor,payload['title'],payload['kind'],payload['split'],cases,parent)
        row.dataset_id=result.id;row.confirmation_note=data.reason.strip();row.confirmed_at=time.time()
        audit(db,actor,'lab.import.confirmed',row.id,result.id)
        return dataset_view(result,True)

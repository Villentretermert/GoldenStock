"""Private, revision-fenced mapping drafts become immutable template versions."""
import asyncio
import json
import re
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate, audit
from goldenstock.models import WorkbookMapping, ModelTemplate, TemplateVersion, User, new_id
from goldenstock.storage import FileStore
from goldenstock.templates import digest, version_view, access
from goldenstock.calculation_engine import canonical, checksum
from goldenstock.template_contract import clean_workbook
from goldenstock.workbook_mapping import Mapping, inspect_workbook, preview, BANK_METRICS

router=APIRouter(prefix='/api/v1/workbook-maps')


def private(db,actor,ident):
    row=db.scalar(select(WorkbookMapping).where(WorkbookMapping.id==ident,WorkbookMapping.org_id==actor.org_id,
        WorkbookMapping.owner_id==actor.id).with_for_update())
    if not row: raise HTTPException(404,'Workbook map not found')
    return row


def receipt(row):
    return dict(id=row.id,title=row.title,revision=row.revision,parent_id=row.parent_id,version_id=row.version_id,created=row.created)


def checked_store(row,request):
    store=FileStore(request.app.state.settings.data_dir)
    if not store.path(row.blob_key).is_file() or store.checksum(row.blob_key)!=row.sha256: raise HTTPException(409,'Workbook integrity check failed')
    return store


def review(db,row):
    parent=db.get(WorkbookMapping,row.parent_id) if row.parent_id else None
    return preview(json.loads(row.inspection),json.loads(row.entries),json.loads(parent.entries) if parent else None)


@router.get('')
def listing(request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        return [receipt(row) for row in db.scalars(select(WorkbookMapping).where(WorkbookMapping.org_id==actor.org_id,
            WorkbookMapping.owner_id==actor.id).order_by(WorkbookMapping.created.desc()).limit(200))]


@router.post('',status_code=201)
async def upload(request:Request):
    actor=authenticate(request,True);idem=request.headers.get('idempotency-key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',idem): raise HTTPException(422,'Valid Idempotency-Key required')
    async with request.form(max_files=1,max_fields=2,max_part_size=1024) as data:
        file=data.get('file');title=str(data.get('title','')).strip();parent_id=str(data.get('parent_id',''))
        if not isinstance(file,UploadFile) or not (file.filename or '').lower().endswith('.xlsx'): raise HTTPException(422,'Upload an XLSX workbook')
        if not 1<=len(title)<=160: raise HTTPException(422,'Title must contain 1–160 characters')
        raw=await file.read(request.app.state.settings.max_file_bytes+1)
    inspection=await asyncio.to_thread(inspect_workbook,raw);fingerprint=checksum([title,parent_id,digest(raw)])
    with Session(request.app.state.engine) as db,db.begin():
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        old=db.scalar(select(WorkbookMapping).where(WorkbookMapping.owner_id==actor.id,WorkbookMapping.idem_key==idem))
        if old:
            if old.request_hash!=fingerprint: raise HTTPException(409,'Idempotency key belongs to another workbook')
            return receipt(old)
        entries=[]
        if parent_id:
            parent=private(db,actor,parent_id)
            if not parent.version_id: raise HTTPException(409,'Finalize the previous mapping first')
            entries=json.loads(parent.entries)
            # Removed/hidden sheets remain visible as unresolved changes in the new draft.
        ident=new_id();blob=f'{actor.org_id}/workbook-maps/{ident}.xlsx'
        FileStore(request.app.state.settings.data_dir).write(blob,raw)
        row=WorkbookMapping(id=ident,org_id=actor.org_id,owner_id=actor.id,title=title,parent_id=parent_id or None,
            idem_key=idem,request_hash=fingerprint,blob_key=blob,sha256=digest(raw),inspection=canonical(inspection),entries=canonical(entries))
        db.add(row);db.flush();audit(db,actor,'workbook.upload',ident,'private')
        return receipt(row)


@router.get('/{ident}')
def detail(ident:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=private(db,actor,ident);checked_store(row,request)
        try: result=review(db,row)
        except HTTPException as exc: result=dict(rows=[],errors=[str(exc.detail)],contract=None,hash=None,omitted_formulas=[],removed=[])
        version=db.get(TemplateVersion,row.version_id) if row.version_id else None
        return dict(receipt(row),inspection=json.loads(row.inspection),entries=json.loads(row.entries),preview=result,
                    template_id=version.template_id if version else None,metrics=BANK_METRICS)


@router.get('/{ident}/original')
def original(ident:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=private(db,actor,ident);store=checked_store(row,request)
        return FileResponse(store.path(row.blob_key),filename='private-workbook.xlsx')


class Edit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=1)
    mapping:Mapping


class Delete(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=1)
    key:str=Field(min_length=1,max_length=40)


class Confirm(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=1)
    preview_hash:str=Field(min_length=64,max_length=64)
    keys:list[str]=Field(max_length=40)
    confirmed:Literal[True]


class Finalize(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=1)
    preview_hash:str=Field(min_length=64,max_length=64)
    acknowledge_omitted:Literal[True]


def fence(row,revision):
    if row.version_id: raise HTTPException(409,'Finalized mapping is immutable; upload a new workbook version')
    if row.revision!=revision: raise HTTPException(409,'Mapping changed; reload the preview')


@router.put('/{ident}/mapping')
def edit(ident:str,data:Edit,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        row=private(db,actor,ident);fence(row,data.revision)
        entries=json.loads(row.entries);mapping=data.mapping.model_dump()
        index=next((i for i,e in enumerate(entries) if e['mapping']['key']==mapping['key']),len(entries))
        entry=dict(mapping=mapping,confirmed=None)
        if index<len(entries) and entries[index]['mapping']==mapping: entry['confirmed']=entries[index].get('confirmed')
        if index==len(entries): entries.append(entry)
        else: entries[index]=entry
        # Structural failures reject the edit; formula diagnostics remain reviewable.
        preview(json.loads(row.inspection),entries)
        row.entries=canonical(entries);row.revision+=1
        audit(db,actor,'workbook.map',ident,mapping['key']);return receipt(row)


@router.delete('/{ident}/mapping')
def remove(ident:str,data:Delete,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        row=private(db,actor,ident);fence(row,data.revision)
        row.entries=canonical([e for e in json.loads(row.entries) if e['mapping']['key']!=data.key]);row.revision+=1
        audit(db,actor,'workbook.remove',ident,data.key);return receipt(row)


@router.post('/{ident}/confirm')
def confirm(ident:str,data:Confirm,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        row=private(db,actor,ident);fence(row,data.revision);checked_store(row,request);result=review(db,row)
        if result['hash']!=data.preview_hash: raise HTTPException(409,'Preview changed; reload')
        rows={r['mapping']['key']:r for r in result['rows']}
        if not data.keys or any(k not in rows or rows[k]['error'] or not rows[k]['fingerprint'] for k in data.keys): raise HTTPException(422,'Select valid mapping rows to confirm')
        entries=json.loads(row.entries)
        for entry in entries:
            key=entry['mapping']['key']
            if key in data.keys: entry['confirmed']=rows[key]['fingerprint']
        row.entries=canonical(entries);row.revision+=1
        audit(db,actor,'workbook.confirm',ident,canonical(data.keys));return receipt(row)


@router.post('/{ident}/finalize',status_code=201)
def finalize(ident:str,data:Finalize,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        row=private(db,actor,ident)
        if row.version_id: return version_view(db.get(TemplateVersion,row.version_id))
        fence(row,data.revision);store=checked_store(row,request);result=review(db,row)
        if result['hash']!=data.preview_hash: raise HTTPException(409,'Preview changed; reload')
        if result['errors'] or not all(r['confirmed'] for r in result['rows']): raise HTTPException(422,'Resolve errors and confirm all changed mappings')
        if row.parent_id:
            parent=private(db,actor,row.parent_id);prior=db.get(TemplateVersion,parent.version_id)
            template=access(db,prior.template_id,actor,True)
            latest=db.scalar(select(TemplateVersion).where(TemplateVersion.template_id==template.id).order_by(TemplateVersion.number.desc()).limit(1))
            if latest.id!=prior.id: raise HTTPException(409,'A newer template version exists; start from its workbook map')
            number=latest.number+1;template.title=row.title;template.shared=False;template.revision+=1
        else:
            template=ModelTemplate(org_id=actor.org_id,owner_id=actor.id,title=row.title);db.add(template);db.flush();number=1
        clean=clean_workbook(result['contract']);ident_version=new_id();clean_key=f'{actor.org_id}/templates/{ident_version}-clean.xlsx'
        store.write(clean_key,clean)
        version=TemplateVersion(id=ident_version,template_id=template.id,owner_id=actor.id,number=number,idem_key='map-'+row.id,
            request_hash=result['hash'],sha256=row.sha256,blob_key=row.blob_key,clean_sha256=digest(clean),clean_key=clean_key,contract=canonical(result['contract']))
        db.add(version);db.flush();row.version_id=version.id;row.revision+=1
        audit(db,actor,'workbook.finalize',row.id,result['hash']);return version_view(version)

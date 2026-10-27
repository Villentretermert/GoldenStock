"""Private originals and deliberately shared template structures, never source facts."""
import asyncio
import hashlib
import json
import re
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import select,update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile
from goldenstock.auth import authenticate,owned,visible,audit
from goldenstock.models import ModelTemplate,TemplateVersion,User,new_id
from goldenstock.storage import FileStore
from goldenstock.template_contract import validate_template,clean_workbook

router=APIRouter(prefix='/api/v1/templates')


def digest(data): return hashlib.sha256(data).hexdigest()


def view(row):
    return dict(id=row.id,title=row.title,owner_id=row.owner_id,shared=row.shared,revision=row.revision)


def version_view(row):
    return dict(id=row.id,template_id=row.template_id,number=row.number,created=row.created,
                clean_sha256=row.clean_sha256,contract=json.loads(row.contract))


def access(db,template_id,actor,write=False):
    # Lock visibility together with version selection so a concurrent private upload
    # cannot become the latest version between authorization and copying/reading.
    row=db.scalar(select(ModelTemplate).where(ModelTemplate.id==template_id,
        visible(ModelTemplate,actor)).with_for_update())
    if row is None or (write and row.owner_id!=actor.id):
        raise HTTPException(404,'Template not found')
    return row


@router.get('')
def listing(request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        return [view(t) for t in db.scalars(select(ModelTemplate).where(visible(ModelTemplate,actor)).order_by(ModelTemplate.title).limit(200))]


@router.get('/demo')
def demo(request:Request):
    authenticate(request)
    return FileResponse(Path(__file__).parent/'assets'/'demo-template.xlsx',filename='goldenstock-demo.xlsx')


@router.post('',status_code=201)
async def upload(request:Request):
    actor=authenticate(request,True)
    idem=request.headers.get('idempotency-key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',idem): raise HTTPException(422,'Valid Idempotency-Key required')
    async with request.form(max_files=1,max_fields=2,max_part_size=1024) as data:
        file=data.get('file');title=str(data.get('title','')).strip();template_id=str(data.get('template_id',''))
        if not isinstance(file,UploadFile) or not file.filename or not file.filename.lower().endswith('.xlsx'):
            raise HTTPException(422,'Upload an XLSX template')
        if not 1<=len(title)<=160: raise HTTPException(422,'Template title must contain 1–160 characters')
        raw=await file.read(request.app.state.settings.max_file_bytes+1)
    contract=await asyncio.to_thread(validate_template,raw)
    clean=await asyncio.to_thread(clean_workbook,contract)
    fingerprint=digest(json.dumps([title,template_id,digest(raw)]).encode())
    with Session(request.app.state.engine) as db,db.begin():
        # Same-owner uploads serialize in PostgreSQL; unique receipts also guard retries.
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        old=db.scalar(select(TemplateVersion).where(TemplateVersion.owner_id==actor.id,TemplateVersion.idem_key==idem))
        if old:
            if old.request_hash!=fingerprint: raise HTTPException(409,'Idempotency key was used for another upload')
            return version_view(old)
        if template_id:
            template=access(db,template_id,actor,True)
            template.title=title
            # New contents must be explicitly shared again by their owner.
            template.shared=False;template.revision+=1
        else:
            template=ModelTemplate(org_id=actor.org_id,owner_id=actor.id,title=title)
            db.add(template);db.flush()
        latest=db.scalar(select(TemplateVersion.number).where(TemplateVersion.template_id==template.id).order_by(TemplateVersion.number.desc()).limit(1)) or 0
        key=new_id();store=FileStore(request.app.state.settings.data_dir)
        original=f'{actor.org_id}/templates/{key}.xlsx';sanitized=f'{actor.org_id}/templates/{key}-clean.xlsx'
        store.write(original,raw);store.write(sanitized,clean)
        row=TemplateVersion(id=key,template_id=template.id,owner_id=actor.id,number=latest+1,
            idem_key=idem,request_hash=fingerprint,sha256=digest(raw),clean_sha256=digest(clean),
            blob_key=original,clean_key=sanitized,contract=json.dumps(contract,sort_keys=True))
        db.add(row)
        try: db.flush()
        except IntegrityError: raise HTTPException(409,'Concurrent upload; retry with the same key') from None
        audit(db,actor,'template.upload',row.id,str(row.number))
        return version_view(row)


@router.get('/{template_id}')
def detail(template_id:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        template=access(db,template_id,actor)
        versions=[version_view(v) for v in db.scalars(select(TemplateVersion).where(TemplateVersion.template_id==template.id).order_by(TemplateVersion.number.desc()))]
        return dict(view(template),versions=versions)


@router.get('/{template_id}/versions/{version_id}/{kind}')
def download(template_id:str,version_id:str,kind:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        template=access(db,template_id,actor,write=kind=='original')
        row=db.scalar(select(TemplateVersion).where(TemplateVersion.id==version_id,TemplateVersion.template_id==template.id))
        if not row or kind not in {'original','structure'}: raise HTTPException(404,'Template version not found')
        key=row.blob_key if kind=='original' else row.clean_key
        expected=row.sha256 if kind=='original' else row.clean_sha256
        store=FileStore(request.app.state.settings.data_dir)
        if not store.path(key).is_file() or store.checksum(key)!=expected:
            raise HTTPException(409,'Template integrity check failed')
        return FileResponse(store.path(key),filename=f'template-v{row.number}-{kind}.xlsx')


class Visibility(BaseModel):
    model_config=ConfigDict(extra='forbid')
    shared: bool
    revision: int=Field(ge=1)


@router.patch('/{template_id}/visibility')
def visibility(template_id:str,data:Visibility,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        # Audit inserts reference User too; keep the same order as upload/copy/calculation.
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        owned(db,ModelTemplate,template_id,actor,True)
        changed=db.execute(update(ModelTemplate).where(ModelTemplate.id==template_id,ModelTemplate.revision==data.revision)
            .values(shared=data.shared,revision=data.revision+1))
        if not changed.rowcount: raise HTTPException(409,'Template changed; reload before sharing')
        audit(db,actor,'template.visibility',template_id,str(data.shared))
        return {'ok':True}


@router.post('/{template_id}/copy',status_code=201)
def copy(template_id:str,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        # Match upload lock order; insertion also checks the owner's foreign key.
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        source=access(db,template_id,actor)
        version=db.scalar(select(TemplateVersion).where(TemplateVersion.template_id==source.id).order_by(TemplateVersion.number.desc()).limit(1))
        if not version: raise HTTPException(409,'No version to copy')
        clone=ModelTemplate(org_id=actor.org_id,owner_id=actor.id,title=('Copy of '+source.title)[:160])
        db.add(clone);db.flush()
        # Copy only the safe artifact; private original data never enters this branch.
        store=FileStore(request.app.state.settings.data_dir)
        if not store.path(version.clean_key).is_file() or store.checksum(version.clean_key)!=version.clean_sha256:
            raise HTTPException(409,'Template integrity check failed')
        key=new_id();blob=f'{actor.org_id}/templates/{key}.xlsx'
        store.write(blob,store.path(version.clean_key).read_bytes())
        db.add(TemplateVersion(template_id=clone.id,owner_id=actor.id,number=1,idem_key=key,
            request_hash=version.clean_sha256,sha256=version.clean_sha256,clean_sha256=version.clean_sha256,
            blob_key=blob,clean_key=blob,contract=version.contract))
        audit(db,actor,'template.copy',clone.id,source.id)
        return view(clone)

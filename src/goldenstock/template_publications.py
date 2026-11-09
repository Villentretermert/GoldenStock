"""Version publication and fund-only delivery; private workbook inputs never enter payloads."""
import hashlib
import json
import time
from fastapi import APIRouter,HTTPException,Request
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate,audit,visible
from goldenstock.models import ModelTemplate,TemplateVersion,TemplatePublication,TemplateNotification,User

router=APIRouter(prefix='/api/v1/template-updates')


def encoded(data): return json.dumps(data,sort_keys=True,ensure_ascii=False)


def checked(row):
    if hashlib.sha256(row.payload.encode()).hexdigest()!=row.payload_sha256:
        raise HTTPException(409,'Publication checksum mismatch')
    return json.loads(row.payload)


def version_query(template,actor):
    query=select(TemplateVersion).where(TemplateVersion.template_id==template.id)
    if template.owner_id!=actor.id:
        query=query.where(TemplateVersion.id.in_(select(TemplatePublication.version_id).where(
            TemplatePublication.template_id==template.id,TemplatePublication.org_id==actor.org_id)))
    return query


def changes(before,after,old_title,title):
    if before is None: return [f'First publication: {len(after["fields"])} mapped fields.']
    result=[]
    if old_title!=title: result.append('Template title changed.')
    if before['policy']!=after['policy']: result.append('Template contract policy changed.')
    previous={f['key']:f for f in before['fields']};current={f['key']:f for f in after['fields']}
    for key in sorted(previous.keys()|current.keys()):
        if key not in previous: result.append('Added field: '+key)
        elif key not in current: result.append('Removed field: '+key)
        else:
            fields=[k for k in sorted(previous[key].keys()|current[key].keys()) if previous[key].get(k)!=current[key].get(k)]
            if fields: result.append('Changed '+key+': '+', '.join(fields))
    return result or ['No changes to the shared structure. Private inputs and notes are excluded.']


def preview(db,template,version):
    existing=db.scalar(select(TemplatePublication).where(TemplatePublication.version_id==version.id))
    if existing: return dict(checked(existing),already_published=True)
    previous=db.scalar(select(TemplatePublication).join(TemplateVersion,TemplatePublication.version_id==TemplateVersion.id)
        .where(TemplatePublication.template_id==template.id).order_by(TemplateVersion.number.desc()).limit(1))
    old=db.get(TemplateVersion,previous.version_id) if previous else None
    return dict(title=template.title,number=version.number,previous_number=old.number if old else None,
        clean_sha256=version.clean_sha256,changes=changes(json.loads(old.contract) if old else None,
        json.loads(version.contract),checked(previous)['title'] if previous else None,template.title),already_published=False)


def publish(db,template,version,actor):
    # Caller holds the template lock. Unique version/recipient receipts fence retries.
    existing=db.scalar(select(TemplatePublication).where(TemplatePublication.version_id==version.id))
    if existing: checked(existing);return existing
    data=preview(db,template,version);data.pop('already_published');payload=encoded(data)
    row=TemplatePublication(org_id=actor.org_id,template_id=template.id,version_id=version.id,
        publisher_id=actor.id,payload=payload,payload_sha256=hashlib.sha256(payload.encode()).hexdigest())
    db.add(row);db.flush()
    for user_id in db.scalars(select(User.id).where(User.org_id==actor.org_id,User.active.is_(True))):
        db.add(TemplateNotification(org_id=actor.org_id,owner_id=user_id,publication_id=row.id))
    audit(db,actor,'template.published',row.id,str(version.number))
    return row


def query(actor):
    return select(TemplateNotification,TemplatePublication).join(TemplatePublication,
        TemplateNotification.publication_id==TemplatePublication.id).join(ModelTemplate,
        TemplatePublication.template_id==ModelTemplate.id).where(TemplateNotification.org_id==actor.org_id,
        TemplateNotification.owner_id==actor.id,TemplatePublication.org_id==actor.org_id,visible(ModelTemplate,actor))


def count(db,actor):
    return db.scalar(select(func.count()).select_from(query(actor).where(TemplateNotification.read_at.is_(None)).subquery()))


@router.get('')
def notifications(request:Request,offset:int=0,unread:bool=False):
    actor=authenticate(request)
    if not 0<=offset<=100000: raise HTTPException(422,'Invalid offset')
    with Session(request.app.state.engine) as db:
        statement=query(actor)
        if unread: statement=statement.where(TemplateNotification.read_at.is_(None))
        rows=list(db.execute(statement.order_by(TemplatePublication.created.desc(),TemplateNotification.id).offset(offset).limit(51)))
        return dict(unread_count=count(db,actor),has_more=len(rows)>50,items=[dict(id=n.id,read_at=n.read_at,
            publication_id=p.id,template_id=p.template_id,version_id=p.version_id,created=p.created,detail=checked(p)) for n,p in rows[:50]])


@router.post('/{key}/read')
def mark_read(key:str,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        found=db.execute(query(actor).where(TemplateNotification.id==key).with_for_update(of=TemplateNotification)).first()
        if not found: raise HTTPException(404,'Template update not found')
        row,_=found
        if row.read_at is None: row.read_at=time.time();audit(db,actor,'template_notification.read',row.id)
        return dict(id=row.id,read_at=row.read_at)

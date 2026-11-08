"""Exact public comparisons and append-only source history; no model inputs change."""
import hashlib
import json
import re
from decimal import Decimal,localcontext
from fastapi import APIRouter,HTTPException,Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate
from goldenstock.models import MonitorFactVersion,MonitorSource,MonitorObservation
from goldenstock.monitor_index import encode,sha

router=APIRouter(prefix='/api/v1/monitoring')
IDENTITY=('namespace','tag','unit','start','end')


def identity(item): return sha([item[k] for k in IDENTITY])


def compare(before,after):
    result=dict(comparable=False,delta=None,percent=None,significant=False,threshold_percent='5',reason='new_metric_period')
    if not before: return result
    if any(before.get(k)!=after.get(k) for k in IDENTITY): return result|dict(reason='different_context')
    for field in ('definition','scope'):
        if before.get(field) is not None and after.get(field) is not None and before[field]!=after[field]:
            return result|dict(reason='different_context')
    # 400 digits cover the bounded SEC tokens and avoid the ambient Decimal precision.
    with localcontext() as ctx:
        ctx.prec=400
        previous,current=Decimal(before['value']),Decimal(after['value'])
        difference=current-previous
        delta=format(difference,'f')
        if '.' in delta: delta=delta.rstrip('0').rstrip('.')
        if difference==0: delta='0'
        if previous==0: return result|dict(comparable=True,delta=delta,reason='zero_baseline')
        percentage=difference/abs(previous)*100
        return result|dict(comparable=True,delta=delta,percent=format(percentage.quantize(Decimal('.01')),'f'),
            significant=abs(difference)*100>=abs(previous)*5,reason='same_context')


def checked(row):
    if hashlib.sha256(row.payload.encode()).hexdigest()!=row.payload_sha256:
        raise HTTPException(409,'Monitoring history checksum mismatch')
    return json.loads(row.payload)


def record(db,source,key,snapshot,after,old,reason,now):
    previous=db.get(MonitorFactVersion,old.history_id) if old and old.history_id else None
    if old and old.history_id and not previous: raise HTTPException(409,'Monitoring history is missing')
    if previous:
        checked(previous)
        if previous.source_id!=source.id or previous.item_key!=key: raise HTTPException(409,'Monitoring history identity mismatch')
        if previous.snapshot_id==snapshot.id and checked(previous)==after: return previous
    payload=encode(after)
    row=MonitorFactVersion(source_id=source.id,item_key=key,revision=previous.revision+1 if previous else 1,
        previous_id=previous.id if previous else None,snapshot_id=snapshot.id,reason=reason,payload=payload,
        payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),created=now)
    db.add(row);db.flush();return row


def view(row):
    return dict(id=row.id,revision=row.revision,previous_id=row.previous_id,snapshot_id=row.snapshot_id,
        reason=row.reason,created=row.created,value=checked(row))


def source(db,key):
    row=db.get(MonitorSource,key)
    if not row or row.kind!='facts': raise HTTPException(404,'Public facts source not found')
    return row


@router.get('/{source_id}/values')
def values(source_id:str,request:Request,offset:int=0):
    authenticate(request)
    if not 0<=offset<=100000: raise HTTPException(422,'Invalid offset')
    with Session(request.app.state.engine) as db:
        row=source(db,source_id)
        observations=list(db.scalars(select(MonitorObservation).where(MonitorObservation.source_id==row.id)
            .order_by(MonitorObservation.item_key).offset(offset).limit(51)))
        return dict(source_id=row.id,company_id=row.company_id,has_more=len(observations)>50,
            items=[dict(item_key=o.item_key,value=json.loads(o.payload),snapshot_id=o.snapshot_id) for o in observations[:50]])


@router.get('/{source_id}/history/{item_key}')
def history(source_id:str,item_key:str,request:Request,offset:int=0):
    authenticate(request)
    if not re.fullmatch('[a-f0-9]{64}',item_key) or not 0<=offset<=100000: raise HTTPException(422,'Invalid history cursor')
    with Session(request.app.state.engine) as db:
        row=source(db,source_id)
        observation=db.get(MonitorObservation,(row.id,item_key))
        if not observation: raise HTTPException(404,'Observed metric not found')
        rows=list(db.scalars(select(MonitorFactVersion).where(MonitorFactVersion.source_id==row.id,
            MonitorFactVersion.item_key==item_key).order_by(MonitorFactVersion.revision.desc()).offset(offset).limit(21)))
        return dict(source_id=row.id,company_id=row.company_id,item_key=item_key,has_more=len(rows)>20,
            items=[view(r) for r in rows[:20]],scope='History observed by this pilot; earlier disclosures may be missing')

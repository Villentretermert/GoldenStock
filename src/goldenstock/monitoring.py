"""Public reporting checks with atomic observations and private website delivery."""
import hashlib
import json
import time
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import Response
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate,audit
from goldenstock.models import (Company,Favorite,User,MonitorSource,MonitorSnapshot,
    MonitorObservation,MonitorEvent,SiteNotification)
from goldenstock.public_sources import fetch,CIKS
from goldenstock.monitor_index import index,semantic,encode,sha,POLICY

router=APIRouter(prefix='/api/v1')
INTERVAL=6*3600
MANUAL_COOLDOWN=900


def followers(db,company):
    return list(db.scalars(select(User).join(Favorite,Favorite.user_id==User.id).where(Favorite.company_id==company,User.active.is_(True))))


def deliver(db,source,kind,fingerprint,payload,now):
    existing=db.scalar(select(MonitorEvent).where(MonitorEvent.source_id==source.id,MonitorEvent.fingerprint==fingerprint))
    if existing: return
    event=MonitorEvent(source_id=source.id,kind=kind,fingerprint=fingerprint,payload=encode(dict(payload,policy=POLICY)),created=now)
    db.add(event);db.flush()
    for user in followers(db,source.company_id):
        db.add(SiteNotification(org_id=user.org_id,owner_id=user.id,event_id=event.id))


def process_monitor(engine,settings,fetcher=None,now=None):
    """One bounded request/transaction. A crash rolls back state and delivery together."""
    now=time.time() if now is None else now
    with Session(engine) as db,db.begin():
        # Shared SEC request lock also used by public summaries. Worker heartbeat runs separately.
        db.scalar(select(Company).where(Company.id=='sber').with_for_update())
        watched=select(Favorite.company_id).join(User,User.id==Favorite.user_id).where(User.active.is_(True)).distinct()
        source=db.scalar(select(MonitorSource).where(MonitorSource.company_id.in_(watched),MonitorSource.next_check<=now).order_by(MonitorSource.next_check,MonitorSource.id).limit(1).with_for_update())
        if not source: return False
        source.last_attempt=now
        try:
            url,raw,_=(fetcher or fetch)(source.company_id,settings.sec_contact,kind=source.kind)
            if len(raw)>20*1024*1024: raise ValueError('Response size limit')
            entries=index(source.company_id,source.kind,raw,now)
            raw.decode('utf-8')
        except Exception as exc:
            # No response text, contact email, SQL error or exception detail enters the feed.
            error='contact_required' if isinstance(exc,HTTPException) and exc.status_code==409 else 'source_unavailable' if isinstance(exc,HTTPException) else 'invalid_source_data'
            if not source.error:
                deliver(db,source,'source_error',sha(['error',source.last_success,now]),dict(error=error),now)
            source.error=error;source.failures+=1
            source.next_check=now+(INTERVAL if error=='contact_required' else min(INTERVAL,300*2**min(source.failures-1,7)))
            return True
        digest=hashlib.sha256(raw).hexdigest()
        snapshot=db.scalar(select(MonitorSnapshot).where(MonitorSnapshot.source_id==source.id,MonitorSnapshot.sha256==digest))
        if not snapshot:
            snapshot=MonitorSnapshot(source_id=source.id,sha256=digest,url=url,payload=raw.decode('utf-8'),created=now)
            db.add(snapshot);db.flush()
        baseline=source.last_success is None
        known={r.item_key:r for r in db.scalars(select(MonitorObservation).where(MonitorObservation.source_id==source.id))}
        for key,after in entries.items():
            old=known.get(key);before=json.loads(old.payload) if old else None
            if source.kind=='facts' and before and (after['filed'],after['accession'])<(before['filed'],before['accession']):
                continue  # An older upstream response cannot revert the latest disclosure.
            changed=before is None or semantic(source.kind,before)!=semantic(source.kind,after)
            if changed and not baseline:
                if source.kind=='submissions':
                    kind='filing_metadata_changed' if before else 'amended_filing' if after['form'].endswith('/A') else 'new_filing'
                    if '4.02' in after.get('items',''): kind='nonreliance_disclosure'
                else: kind='possible_revision' if before else 'new_metric_period'
                deliver(db,source,kind,sha([key,semantic(source.kind,after)]),
                    dict(before=before,after=after,before_snapshot_id=old.snapshot_id if old else None,after_snapshot_id=snapshot.id),now)
            if not old: db.add(MonitorObservation(source_id=source.id,item_key=key,payload=encode(after),snapshot_id=snapshot.id))
            else: old.payload=encode(after);old.snapshot_id=snapshot.id
        if source.error:
            deliver(db,source,'source_recovered',sha(['recovered',source.last_success,now]),dict(snapshot_id=snapshot.id),now)
        source.snapshot_id=snapshot.id;source.last_success=now;source.next_check=now+INTERVAL;source.error='';source.failures=0
    return True


@router.get('/monitoring')
def status(request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        favorites=set(db.scalars(select(Favorite.company_id).where(Favorite.user_id==actor.id)))
        rows=list(db.scalars(select(MonitorSource)));result=[]
        for company in db.scalars(select(Company).order_by(Company.name)):
            sources=[dict(id=s.id,kind=s.kind,last_attempt=s.last_attempt,last_success=s.last_success,
                next_check=s.next_check,error=s.error,failures=s.failures,snapshot_id=s.snapshot_id,
                known_items=db.scalar(select(func.count()).select_from(MonitorObservation).where(MonitorObservation.source_id==s.id))) for s in rows if s.company_id==company.id]
            attempts=[s['last_attempt'] for s in sources if s['last_attempt'] is not None]
            result.append(dict(company_id=company.id,name=company.name,following=company.id in favorites,
                coverage='sec_selected' if company.id in CIKS else 'english_connector_gap',sources=sources,
                can_check=company.id in favorites and company.id in CIKS and (not attempts or time.time()-max(attempts)>=MANUAL_COOLDOWN)))
        from goldenstock.monitor_worker import healthy
        return dict(interval_seconds=INTERVAL,companies=result,scheduler_ready=healthy(request.app.state.engine,request.app.state.settings.heartbeat_timeout))


@router.post('/monitoring/{company_id}/check',status_code=202)
def check(company_id:str,request:Request):
    actor=authenticate(request,True);now=time.time()
    with Session(request.app.state.engine) as db,db.begin():
        db.scalar(select(Company).where(Company.id=='sber').with_for_update())
        if company_id not in CIKS: raise HTTPException(409,'No verified English monitoring connector for this company')
        if not db.get(Favorite,(actor.id,company_id)): raise HTTPException(409,'Add the company to your watchlist first')
        rows=list(db.scalars(select(MonitorSource).where(MonitorSource.company_id==company_id).with_for_update()))
        if any(s.last_attempt is not None and now-s.last_attempt<MANUAL_COOLDOWN for s in rows): raise HTTPException(429,'A check was attempted recently; retry after 15 minutes or wait for the schedule')
        for source in rows: source.next_check=min(source.next_check,now)
        audit(db,actor,'monitor.requested',company_id)
        return dict(queued=True)


@router.get('/notifications')
def notifications(request:Request,offset:int=0,unread:bool=False):
    actor=authenticate(request)
    if not 0<=offset<=100000: raise HTTPException(422,'Invalid offset')
    with Session(request.app.state.engine) as db:
        private=(SiteNotification.org_id==actor.org_id)&(SiteNotification.owner_id==actor.id)
        query=select(SiteNotification,MonitorEvent,MonitorSource).join(MonitorEvent,SiteNotification.event_id==MonitorEvent.id).join(MonitorSource,MonitorEvent.source_id==MonitorSource.id).where(private)
        if unread: query=query.where(SiteNotification.read_at.is_(None))
        count=db.scalar(select(func.count()).select_from(SiteNotification).where(private,SiteNotification.read_at.is_(None)))
        rows=list(db.execute(query.order_by(MonitorEvent.created.desc(),SiteNotification.id).offset(offset).limit(51)))
        return dict(unread_count=count,has_more=len(rows)>50,items=[dict(id=n.id,read_at=n.read_at,company_id=s.company_id,
            source_kind=s.kind,kind=ev.kind,created=ev.created,detail=json.loads(ev.payload)) for n,ev,s in rows[:50]])


@router.get('/notifications/count')
def unread_count(request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        count=db.scalar(select(func.count()).select_from(SiteNotification).where(SiteNotification.org_id==actor.org_id,
            SiteNotification.owner_id==actor.id,SiteNotification.read_at.is_(None)))
        return dict(unread_count=count)


@router.post('/notifications/{key}/read')
def mark_read(key:str,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        row=db.scalar(select(SiteNotification).where(SiteNotification.id==key,SiteNotification.org_id==actor.org_id,SiteNotification.owner_id==actor.id).with_for_update())
        if not row: raise HTTPException(404,'Notification not found')
        if row.read_at is None: row.read_at=time.time();audit(db,actor,'notification.read',row.id)
        return dict(id=row.id,read_at=row.read_at)


@router.get('/monitor-snapshots/{key}/download')
def download(key:str,request:Request):
    authenticate(request)
    with Session(request.app.state.engine) as db:
        row=db.get(MonitorSnapshot,key)
        if not row: raise HTTPException(404,'Public monitoring snapshot not found')
        raw=row.payload.encode('utf-8')
        if hashlib.sha256(raw).hexdigest()!=row.sha256: raise HTTPException(409,'Snapshot checksum mismatch')
        return Response(raw,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="sec-monitor-{row.id}.json"','X-Content-SHA256':row.sha256})

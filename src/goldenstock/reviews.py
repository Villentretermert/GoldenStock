"""Server-side review gate. No valuation approval is implied by a verified input set."""
import hashlib
import json
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from goldenstock.auth import authenticate, audit
from goldenstock.models import Company, Fact, FactReview, InputSnapshot
from goldenstock.facts import private, fact_dict
from goldenstock.normalization import conflicts, POLICY

router=APIRouter(prefix='/api/v1')
REVIEW_POLICY='gs012-v1'


def decision_dict(row):
    return dict(id=row.id,revision=row.revision,actor_id=row.actor_id,decision=row.decision,note=row.note,created=row.created)


def latest_reviews(db,ids):
    result={}
    if ids:
        for row in db.scalars(select(FactReview).where(FactReview.fact_id.in_(ids)).order_by(FactReview.revision)):
            result[row.fact_id]=decision_dict(row)
    return result


def state(db,actor,company_id):
    rows=list(db.scalars(select(Fact).where(private(actor),Fact.company_id==company_id).order_by(Fact.id)))
    replaced={r.supersedes for r in rows if r.supersedes}
    active=[r for r in rows if r.id not in replaced]
    decisions=latest_reviews(db,[r.id for r in active])
    signature=dict(policy=POLICY,review_policy=REVIEW_POLICY,
        facts=[(r.id,r.fingerprint,decisions.get(r.id,{}).get('id')) for r in active])
    digest=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    items=[dict(fact_dict(r),review=decisions.get(r.id),review_status=decisions.get(r.id,{}).get('decision','unreviewed')) for r in active]
    included=[i for i in items if not i['review'] or i['review']['decision']!='rejected']
    queue=conflicts(included)
    blockers=sum(q['severity']=='blocker' for q in queue)
    unreviewed=sum(not i['review'] or i['review']['decision']!='accepted' for i in included)
    return dict(state_hash=digest,facts=items,included=included,conflicts=queue,
        blocker_count=blockers,unreviewed_count=unreviewed,
        ready=bool(included) and not blockers and not unreviewed)


def owned_fact(db,actor,fact_id):
    row=db.scalar(select(Fact).where(private(actor),Fact.id==fact_id))
    if not row: raise HTTPException(404,'Fact not found')
    return row


class ReviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision: int=Field(ge=0)
    decision: Literal['accepted','rejected','unreviewed']
    note: str=Field(min_length=3,max_length=2000)


@router.post('/facts/{fact_id}/reviews',status_code=201)
def review_fact(fact_id: str,data: ReviewInput,request: Request):
    actor=authenticate(request,True)
    note=data.note.strip()
    if len(note)<3: raise HTTPException(422,'Explain the decision after checking the source and warnings')
    try:
        with Session(request.app.state.engine) as db,db.begin():
            row=owned_fact(db,actor,fact_id)
            # Same lock as fact creation and snapshots makes the input gate atomic in PostgreSQL.
            db.scalar(select(Company).where(Company.id==row.company_id).with_for_update())
            if db.scalar(select(Fact.id).where(Fact.supersedes==fact_id)):
                raise HTTPException(409,'Review the current fact version')
            latest=latest_reviews(db,[fact_id]).get(fact_id)
            revision=latest['revision'] if latest else 0
            if data.expected_revision!=revision: raise HTTPException(409,'Review changed; refresh before deciding')
            entry=FactReview(fact_id=fact_id,revision=revision+1,actor_id=actor.id,decision=data.decision,note=note)
            db.add(entry);db.flush()
            audit(db,actor,'fact.review',fact_id,'review='+entry.id+';decision='+data.decision)
            return decision_dict(entry)
    except IntegrityError:
        raise HTTPException(409,'Concurrent review; refresh') from None


@router.get('/facts/{fact_id}/reviews')
def review_history(fact_id: str,request: Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        owned_fact(db,actor,fact_id)
        return [decision_dict(r) for r in db.scalars(select(FactReview).where(FactReview.fact_id==fact_id).order_by(FactReview.revision))]


@router.get('/review-state')
def review_state(request: Request,company_id: str):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        if not db.get(Company,company_id): raise HTTPException(404,'Company not found')
        result=state(db,actor,company_id)
        return dict(state_hash=result['state_hash'],ready=result['ready'],blocker_count=result['blocker_count'],
            unreviewed_count=result['unreviewed_count'],included_count=len(result['included']),
            facts=result['facts'],conflicts=result['conflicts'][:200],conflict_count=len(result['conflicts']))


class SnapshotInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    company_id: str=Field(max_length=32)
    title: str=Field(min_length=1,max_length=160)
    expected_state_hash: str=Field(min_length=64,max_length=64)


@router.post('/input-snapshots',status_code=201)
def save_snapshot(data: SnapshotInput,request: Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        company=db.scalar(select(Company).where(Company.id==data.company_id).with_for_update())
        if not company: raise HTTPException(404,'Company not found')
        result=state(db,actor,company.id)
        if data.expected_state_hash!=result['state_hash']:
            raise HTTPException(409,'Facts or decisions changed; refresh the review')
        if not result['ready']:
            raise HTTPException(409,'Confirm all included facts and resolve profit/equity conflicts before saving')
        old=db.scalar(select(InputSnapshot).where(InputSnapshot.org_id==actor.org_id,InputSnapshot.owner_id==actor.id,
            InputSnapshot.company_id==company.id,InputSnapshot.state_hash==result['state_hash']))
        if old: return {'id':old.id,'status':'verified_inputs'}
        payload=dict(policy=POLICY,review_policy=REVIEW_POLICY,status='verified_inputs',facts=result['included'],
            excluded=[f for f in result['facts'] if f not in result['included']],warnings=result['conflicts'],
            scope='Active private facts of this analyst and company; not a complete financial model')
        row=InputSnapshot(org_id=actor.org_id,owner_id=actor.id,company_id=company.id,title=data.title,
            state_hash=result['state_hash'],payload=json.dumps(payload,ensure_ascii=True))
        db.add(row);db.flush();audit(db,actor,'inputs.snapshot',row.id,'state='+row.state_hash)
        return {'id':row.id,'status':'verified_inputs'}


@router.get('/input-snapshots')
def snapshots(request: Request,company_id: str):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        current=state(db,actor,company_id)
        return [dict(id=r.id,title=r.title,created=r.created,current=r.state_hash==current['state_hash']) for r in db.scalars(
            select(InputSnapshot).where(InputSnapshot.org_id==actor.org_id,InputSnapshot.owner_id==actor.id,
                InputSnapshot.company_id==company_id).order_by(InputSnapshot.created.desc()))]


@router.get('/input-snapshots/{snapshot_id}')
def snapshot(snapshot_id: str,request: Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=db.scalar(select(InputSnapshot).where(InputSnapshot.id==snapshot_id,
            InputSnapshot.org_id==actor.org_id,InputSnapshot.owner_id==actor.id))
        if not row: raise HTTPException(404,'Input set not found')
        current=state(db,actor,row.company_id)
        return dict(id=row.id,title=row.title,created=row.created,current=row.state_hash==current['state_hash'],
            eligible_for_future_calculation=row.state_hash==current['state_hash'] and current['ready'],
            snapshot=json.loads(row.payload))

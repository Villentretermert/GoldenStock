"""Private, append-only normalized facts tied to immutable extracted evidence."""
import hashlib
import json
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from goldenstock.auth import authenticate, audit
from goldenstock.documents import authorized_job
from goldenstock.models import Fact, Extraction, DocumentVersion, Document, Company
from goldenstock.normalization import FactInput, normalize, conflicts, METRICS, POLICY

router=APIRouter(prefix='/api/v1')


def private(actor):
    return (Fact.org_id==actor.org_id)&(Fact.owner_id==actor.id)


def fact_dict(fact):
    return dict(json.loads(fact.payload),id=fact.id,company_id=fact.company_id,
                version_id=fact.version_id,created=fact.created)


@router.get('/metrics')
def metrics(request: Request):
    authenticate(request)
    return dict(policy=POLICY,metrics=[dict(id=k,title=v[0],kind=v[1],timing=v[2],definition=v[3],
        priority='core' if k not in {'mau','ltv'} else 'optional') for k,v in METRICS.items()])


@router.post('/facts',status_code=201)
def create_fact(data: FactInput,request: Request):
    actor=authenticate(request,True)
    try:
        with Session(request.app.state.engine) as db,db.begin():
            job=authorized_job(db,data.job_id,actor)
            version=db.get(DocumentVersion,job.version_id)
            if version.owner_id!=actor.id:
                raise HTTPException(404,'Private evidence not found')
            extraction=db.get(Extraction,version.id)
            if not extraction: raise HTTPException(409,'Extract the document first')
            source=json.loads(extraction.payload)
            if data.item_index>=len(source['items']): raise HTTPException(422,'Evidence item not found')
            try:
                payload=normalize(data,source['items'][data.item_index])
            except ValueError as exc:
                raise HTTPException(422,str(exc)) from None
            doc=db.get(Document,version.document_id)
            payload.update(source_sha256=extraction.source_sha256,parser_version=extraction.parser_version,
                           document_id=doc.id,filename=version.filename)
            encoded=json.dumps(payload,sort_keys=True,ensure_ascii=True)
            fingerprint=hashlib.sha256((version.id+encoded).encode()).hexdigest()
            old=db.scalar(select(Fact).where(private(actor),Fact.fingerprint==fingerprint))
            if old: return fact_dict(old)
            # Serialize append/quota checks per issuer; private values never enter this common row.
            db.scalar(select(Company).where(Company.id==doc.company_id).with_for_update())
            if db.scalar(select(func.count()).select_from(Fact).where(private(actor),Fact.company_id==doc.company_id))>=500:
                raise HTTPException(409,'Pilot limit: 500 fact versions per analyst and company')
            if data.supersedes:
                previous=db.scalar(select(Fact).where(private(actor),Fact.id==data.supersedes,Fact.company_id==doc.company_id))
                if not previous: raise HTTPException(404,'Previous fact not found')
                if db.scalar(select(Fact.id).where(Fact.supersedes==previous.id)):
                    raise HTTPException(409,'Fact already superseded; refresh history')
            item=Fact(org_id=actor.org_id,owner_id=actor.id,company_id=doc.company_id,version_id=version.id,
                      fingerprint=fingerprint,supersedes=data.supersedes or None,payload=encoded)
            db.add(item); db.flush()
            audit(db,actor,'fact.create',item.id,'source='+version.id+';policy='+POLICY)
            return fact_dict(item)
    except IntegrityError:
        with Session(request.app.state.engine) as db:
            old=db.scalar(select(Fact).where(private(actor),Fact.fingerprint==fingerprint))
            if old: return fact_dict(old)
        raise HTTPException(409,'Concurrent fact revision; refresh and retry') from None


@router.get('/facts')
def facts(request: Request,company_id: str,history: bool=False):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        if not db.get(Company,company_id): raise HTTPException(404,'Company not found')
        rows=list(db.scalars(select(Fact).where(private(actor),Fact.company_id==company_id).order_by(Fact.created,Fact.id)))
        replaced={r.supersedes for r in rows if r.supersedes}
        from goldenstock.reviews import latest_reviews
        decisions=latest_reviews(db,[r.id for r in rows])
        return [dict(fact_dict(r),active=r.id not in replaced,
            review_status=decisions.get(r.id,{}).get('decision','unreviewed')) for r in rows if history or r.id not in replaced]


@router.get('/facts/{fact_id}')
def fact(fact_id: str,request: Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=db.scalar(select(Fact).where(private(actor),Fact.id==fact_id))
        if not row: raise HTTPException(404,'Fact not found')
        from goldenstock.reviews import latest_reviews
        latest=latest_reviews(db,[row.id]).get(row.id,{})
        return dict(fact_dict(row),review_status=latest.get('decision','unreviewed'))


@router.get('/conflicts')
def conflict_queue(request: Request,company_id: str):
    items=[f for f in facts(request,company_id) if f['review_status']!='rejected']
    queue=conflicts(items)
    return dict(policy=POLICY,tolerance='explicit_source_rounding_intervals',relative_tolerance='0',
        total=len(queue),items=queue[:200],truncated=len(queue)>200,
        blocker_count=sum(c['severity']=='blocker' for c in queue),
        approval_implemented=False,input_review_implemented=True,missing_metrics=[m for m in METRICS if m not in {i['metric'] for i in items}])

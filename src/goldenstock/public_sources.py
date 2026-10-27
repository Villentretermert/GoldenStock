"""Fixed SEC companyfacts connector, shared public provenance, no arbitrary URLs."""
import hashlib
import json
import re
import time
from datetime import date
from decimal import Decimal
import httpx
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate
from goldenstock.models import Company,PublicSnapshot

router=APIRouter(prefix='/api/v1/public-snapshots')
CIKS={'jpm':19617,'hsbc':1089113,'nu':1691493}
TAGS=('ProfitLossAttributableToOwnersOfParent','NetIncomeLoss','Equity',
      'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest','Assets')


def fetch(company,contact,transport=None):
    if company not in CIKS: raise HTTPException(409,'English SEC coverage is unavailable for this company')
    if not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+',contact) or len(contact)>200:
        raise HTTPException(409,'Configure a real SEC contact email before public-source requests')
    cik=CIKS[company];url=f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'
    start=time.monotonic()
    try:
        with httpx.Client(timeout=15,trust_env=False,follow_redirects=False,transport=transport) as client:
            with client.stream('GET',url,headers={'User-Agent':'GoldenStock pilot '+contact,'Accept':'application/json'}) as response:
                if response.status_code!=200: raise HTTPException(502,'SEC unavailable or access restricted; no substitute data used')
                chunks=[];size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>20*1024*1024 or time.monotonic()-start>30: raise HTTPException(502,'SEC response limit reached')
                    chunks.append(chunk)
        raw=b''.join(chunks);data=json.loads(raw)
        if int(data['cik'])!=cik or not isinstance(data['facts'],dict): raise ValueError()
        return url,raw,data
    except (httpx.HTTPError,ValueError,KeyError,TypeError): raise HTTPException(502,'Invalid or unavailable SEC data') from None
    finally:
        # Called under the database-wide connector lock: at most one request per second.
        remaining=1-(time.monotonic()-start)
        if remaining>0: time.sleep(remaining)


def snapshot(db,company,settings):
    db.scalar(select(Company).where(Company.id=='sber').with_for_update())
    old=db.scalar(select(PublicSnapshot).where(PublicSnapshot.company_id==company).order_by(PublicSnapshot.created.desc()).limit(1))
    if old and time.time()-old.checked<900: return old
    url,raw,data=fetch(company,settings.sec_contact)
    digest=hashlib.sha256(raw).hexdigest()
    identical=db.scalar(select(PublicSnapshot).where(PublicSnapshot.company_id==company,PublicSnapshot.sha256==digest))
    if identical:
        identical.checked=time.time()
        return identical
    row=PublicSnapshot(company_id=company,url=url,sha256=digest,payload=raw.decode('utf-8'))
    db.add(row);db.flush();return row


def evidence(row):
    data=json.loads(row.payload,parse_float=Decimal);result=[];earliest=f'{date.today().year-3}-01-01'
    for tag in TAGS:
        for namespace in ('us-gaap','ifrs-full'):
            concept=data['facts'].get(namespace,{}).get(tag)
            if not concept: continue
            for unit,values in concept.get('units',{}).items():
                candidates=[(i,v) for i,v in enumerate(values) if v.get('end','')>=earliest and v.get('form') in {'10-K','10-Q','20-F','6-K'}]
                if not candidates: continue
                i,v=max(candidates,key=lambda pair:(pair[1]['end'],pair[1].get('filed',''),pair[1].get('start','')))
                text=f"{namespace}:{tag} ({concept.get('label',tag)}): {v['val']} {unit}; period {v.get('start','instant')} to {v['end']}; filed {v.get('filed','unknown')}; accession {v.get('accn','unknown')}. Public XBRL, unreviewed."
                key=hashlib.sha256((row.sha256+namespace+tag+unit+str(i)).encode()).hexdigest()[:32]
                result.append(dict(id=key,text=text,source_url=row.url,source_sha256=row.sha256,
                    snapshot_id=row.id,json_path=f'/facts/{namespace}/{tag}/units/{unit}/{i}',period_end=v['end']))
                if len(result)==4: return result
    return result


@router.get('/{snapshot_id}')
def read(snapshot_id:str,request:Request):
    authenticate(request)
    with Session(request.app.state.engine) as db:
        row=db.get(PublicSnapshot,snapshot_id)
        if not row: raise HTTPException(404,'Public snapshot not found')
        return dict(id=row.id,url=row.url,sha256=row.sha256,retrieved_at=row.created,checked_at=row.checked,data=json.loads(row.payload))


@router.get('/{snapshot_id}/download')
def original(snapshot_id:str,request:Request):
    authenticate(request)
    with Session(request.app.state.engine) as db:
        row=db.get(PublicSnapshot,snapshot_id)
        if not row: raise HTTPException(404,'Public snapshot not found')
        return Response(content=row.payload.encode('utf-8'),media_type='application/json',
            headers={'Content-Disposition':f'attachment; filename="sec-{row.id}.json"'})

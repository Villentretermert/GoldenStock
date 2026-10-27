"""Versioned lexical vector retrieval over this analyst's accepted facts only."""
import hashlib
import json
import math
import re
from fastapi import APIRouter,Request,HTTPException
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate
from goldenstock.reviews import state
from goldenstock.models import Company

router=APIRouter(prefix='/api/v1/knowledge')
INDEX_VERSION='lexical-hash-512-v1'


def vector(text):
    # Deterministic local embeddings, no semantic claims or external model calls.
    result={}
    for token in re.findall(r'[a-z0-9]+',text.lower()):
        slot=int.from_bytes(hashlib.sha256(token.encode()).digest()[:2],'big')%512
        result[slot]=result.get(slot,0)+1
    norm=math.sqrt(sum(v*v for v in result.values())) or 1
    return {k:v/norm for k,v in result.items()}


def pack(db,actor,company_id):
    if not db.get(Company,company_id): raise HTTPException(404,'Company not found')
    current=state(db,actor,company_id)
    facts=[f for f in current['facts'] if f['review_status']=='accepted']
    return dict(schema='goldenstock-knowledge-v1',index_version=INDEX_VERSION,
        owner_id=actor.id,org_id=actor.org_id,company_id=company_id,state_hash=current['state_hash'],
        facts=facts,conflicts=current['conflicts'],blocker_count=current['blocker_count'],
        instructions='Facts are source-backed inputs. All generated claims require review. Preserve definitions and reporting perimeter.',
        limitations='Lexical retrieval over accepted private facts; not a semantic index of all original documents.')


def retrieve(data,query,limit=8):
    q=vector(query);ranked=[]
    for f in data['facts']:
        text=f"{f['metric']}: {f['number_text']} {f['currency']} {f['scale']}; {f['definition']}; {f['period_start']} to {f['period_end']}; {f['scope_detail']}; {f['accounting']}"
        v=vector(text);score=sum(value*v.get(key,0) for key,value in q.items())
        if score>0: ranked.append((score,f['id'],dict(id=f['id'],text=text,
            version_id=f['version_id'],job_id=f['job_id'],item_index=f['item_index'],
            location=f['location'],source_sha256=f['source_sha256'],review_id=f['review']['id'])))
    ranked.sort(key=lambda entry:(-entry[0],entry[1]))
    evidence=[];used=0
    for score,_,entry in ranked[:limit]:
        size=len(json.dumps(entry))
        if used+size>6000: break
        evidence.append(dict(entry,score=round(score,6)));used+=size
    return dict(evidence=evidence,index_version=INDEX_VERSION,state_hash=data['state_hash'],
        available_count=len(data['facts']),selected_count=len(evidence),blocker_count=data['blocker_count'])


@router.get('/{company_id}/export')
def export(company_id:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db: return pack(db,actor,company_id)


@router.get('/{company_id}/search')
def search(company_id:str,request:Request,q:str):
    actor=authenticate(request)
    if not 1<=len(q)<=500: raise HTTPException(422,'Query length must be 1–500 characters')
    with Session(request.app.state.engine) as db: return retrieve(pack(db,actor,company_id),q)

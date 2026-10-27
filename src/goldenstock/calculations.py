"""Private immutable calculations with explicit input provenance and replay receipts."""
import json
import re
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate, audit
from goldenstock.models import CalculationRun, Company, InputSnapshot, TemplateVersion, User
from goldenstock.templates import access
from goldenstock.reviews import state as review_state
from goldenstock.calculation_engine import ENGINE, calculate, canonical, checksum, parse_number, decimal_text

router=APIRouter(prefix='/api/v1/calculations')


class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid')


class InputValue(StrictModel):
    value: str | None = Field(default=None,max_length=80)
    fact_id: str | None = Field(default=None,min_length=1,max_length=32)
    note: str = Field(min_length=3,max_length=1000)
    confirmed: Literal[True]

    @model_validator(mode='after')
    def source(self):
        if (self.value is None)==(self.fact_id is None): raise ValueError('Choose exactly one manual value or verified fact')
        if len(self.note.strip())<3: raise ValueError('Explain and confirm the input mapping or assumption')
        if self.value is not None: parse_number(self.value)
        return self


class ControlCheck(StrictModel):
    key: str=Field(min_length=1,max_length=50)
    expected: str=Field(default='0',max_length=80)
    tolerance: str=Field(default='0',max_length=80)
    note: str=Field(min_length=3,max_length=1000)

    @model_validator(mode='after')
    def numbers(self):
        parse_number(self.expected)
        if parse_number(self.tolerance)<0: raise ValueError('Tolerance must be nonnegative')
        if len(self.note.strip())<3: raise ValueError('Explain the control check and tolerance')
        return self


class CalculationInput(StrictModel):
    title: str=Field(min_length=1,max_length=160)
    company_id: str=Field(min_length=1,max_length=32)
    template_id: str=Field(min_length=1,max_length=32)
    version_id: str=Field(min_length=1,max_length=32)
    snapshot_id: str | None=Field(default=None,min_length=1,max_length=32)
    scenarios: dict[Literal['base','optimistic','stress'],dict[str,InputValue]]=Field(min_length=1,max_length=3)
    checks: list[ControlCheck]=Field(default_factory=list,max_length=20)


def private_run(db,actor,run_id):
    row=db.scalar(select(CalculationRun).where(CalculationRun.id==run_id,
        CalculationRun.org_id==actor.org_id,CalculationRun.owner_id==actor.id))
    if not row: raise HTTPException(404,'Calculation not found')
    return row


def receipt(row):
    return dict(id=row.id,title=row.title,company_id=row.company_id,created=row.created,
                engine=row.engine,state=row.state,input_hash=row.input_hash,result_hash=row.result_hash)


def fact_matches(field,fact):
    unit=fact['currency'] if fact['canonical_unit']=='money' else ('ratio' if fact['canonical_unit']=='fraction' else fact['canonical_unit'])
    # v1 maps calendar-year facts only. Other financial year ends need an explicit future contract.
    year=field['period'][2:] if field['period'].startswith('FY') else ''
    period=(fact['period_end']==year+'-12-31' and
            (fact['period_kind']=='instant' or (fact['period_kind']=='year' and fact['period_start']==year+'-01-01')))
    return field['unit']==unit and period


@router.post('',status_code=201)
def create(data:CalculationInput,request:Request):
    actor=authenticate(request,True)
    idem=request.headers.get('idempotency-key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',idem): raise HTTPException(422,'Valid Idempotency-Key required')
    if not data.title.strip(): raise HTTPException(422,'Title is required')
    if 'base' not in data.scenarios: raise HTTPException(422,'Base scenario is required')
    request_hash=checksum(data.model_dump(mode='json'))
    with Session(request.app.state.engine) as db,db.begin():
        # Consistent lock order with template uploads/copies; Company also fences review changes.
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        old=db.scalar(select(CalculationRun).where(CalculationRun.owner_id==actor.id,CalculationRun.idem_key==idem))
        if old:
            if old.request_hash!=request_hash: raise HTTPException(409,'Idempotency key was used for another calculation')
            return receipt(old)
        company=db.scalar(select(Company).where(Company.id==data.company_id).with_for_update())
        if not company: raise HTTPException(404,'Company not found')
        template=access(db,data.template_id,actor)
        version=db.scalar(select(TemplateVersion).where(TemplateVersion.id==data.version_id,TemplateVersion.template_id==template.id))
        if not version: raise HTTPException(404,'Template version not found')
        contract=json.loads(version.contract)
        inputs={f['key']:f for f in contract['fields'] if f['role']=='input'}
        computed={f['key'] for f in contract['fields'] if f['role']!='input'}
        if any(c.key not in computed for c in data.checks) or len({c.key for c in data.checks})!=len(data.checks):
            raise HTTPException(422,'Control checks must reference distinct calculated fields')
        snapshot=None;facts={}
        if data.snapshot_id:
            snapshot=db.scalar(select(InputSnapshot).where(InputSnapshot.id==data.snapshot_id,
                InputSnapshot.org_id==actor.org_id,InputSnapshot.owner_id==actor.id,InputSnapshot.company_id==company.id))
            if not snapshot: raise HTTPException(404,'Input snapshot not found')
            current=review_state(db,actor,company.id)
            if snapshot.state_hash!=current['state_hash'] or not current['ready']:
                raise HTTPException(409,'Input snapshot is stale or no longer verified; review and save a new set')
            facts={f['id']:f for f in json.loads(snapshot.payload)['facts']}
        resolved={}
        for name,values in data.scenarios.items():
            if set(values)!=set(inputs): raise HTTPException(422,f'{name}: supply every mapped input exactly once; no extra keys')
            resolved[name]={}
            for key,binding in values.items():
                item=dict(actor_id=actor.id,note=binding.note.strip(),confirmed=True)
                if binding.fact_id:
                    fact=facts.get(binding.fact_id)
                    if not fact or fact.get('review_status')!='accepted': raise HTTPException(422,'Choose a fact from the current verified input snapshot')
                    if not fact_matches(inputs[key],fact): raise HTTPException(422,f'{key}: fact currency/unit or calendar year does not match the template')
                    item.update(value=fact['value'],source='verified_fact',fact=fact)
                else: item.update(value=binding.value,source='manual_assumption')
                try: item['value']=decimal_text(parse_number(item['value']))
                except ValueError as exc: raise HTTPException(422,f'{key}: {exc}') from None
                resolved[name][key]=item
        checks=[c.model_dump() for c in data.checks]
        payload=dict(engine=ENGINE,company_id=company.id,template=dict(id=template.id,title=template.title,
            version_id=version.id,number=version.number,clean_sha256=version.clean_sha256,contract=contract),
            snapshot=dict(id=snapshot.id,state_hash=snapshot.state_hash) if snapshot else None,
            scenarios=resolved,checks=checks)
        try: result=calculate(contract,resolved,checks)
        except ValueError as exc: raise HTTPException(422,'Template calculation contract: '+str(exc)) from None
        row=CalculationRun(org_id=actor.org_id,owner_id=actor.id,company_id=company.id,
            version_id=version.id,title=data.title.strip(),engine=ENGINE,idem_key=idem,request_hash=request_hash,
            input_hash=checksum(payload),result_hash=checksum(result),input=canonical(payload),output=canonical(result),state=result['state'])
        db.add(row);db.flush();audit(db,actor,'calculation.create',row.id,'engine='+ENGINE+';state='+row.state)
        return receipt(row)


@router.get('')
def listing(request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        return [receipt(r) for r in db.scalars(select(CalculationRun).where(CalculationRun.org_id==actor.org_id,
            CalculationRun.owner_id==actor.id).order_by(CalculationRun.created.desc()).limit(200))]


def verified_payload(row):
    payload,result=json.loads(row.input),json.loads(row.output)
    if checksum(payload)!=row.input_hash or checksum(result)!=row.result_hash:
        raise HTTPException(409,'Calculation integrity check failed')
    return payload,result


@router.get('/{run_id}')
def detail(run_id:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=private_run(db,actor,run_id);payload,result=verified_payload(row)
        current=None
        if payload['snapshot']:
            review=review_state(db,actor,row.company_id)
            current=review['ready'] and review['state_hash']==payload['snapshot']['state_hash']
        return dict(receipt(row),input=payload,result=result,inputs_current=current)


@router.post('/{run_id}/replay')
def replay(run_id:str,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        row=private_run(db,actor,run_id);payload,_=verified_payload(row)
        if row.engine!=ENGINE: raise HTTPException(409,'Replay requires the original engine version')
        result=calculate(payload['template']['contract'],payload['scenarios'],payload['checks'])
        matched=checksum(result)==row.result_hash
        audit(db,actor,'calculation.replay',row.id,'matched='+str(matched))
        if not matched: raise HTTPException(409,'Replay result differs from the saved receipt')
        return dict(id=row.id,matched=True,result_hash=row.result_hash)

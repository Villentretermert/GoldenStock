"""Private valuation receipts: declared methodology, source calculation and dated quote."""
import json
import re
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate,audit
from goldenstock.models import User,Company,ValuationRun
from goldenstock.calculations import StrictModel,private_run,verified_payload
from goldenstock.reviews import state as review_state
from goldenstock.calculation_engine import ENGINE,canonical,checksum,parse_number
from goldenstock.valuation_engine import POLICY,contract,input_fields,value_scenarios,bound_number

router=APIRouter(prefix='/api/v1/valuations')


class Binding(StrictModel):
    source_key: str | None=Field(default=None,min_length=1,max_length=50)
    value: str | None=Field(default=None,max_length=80)
    note: str=Field(min_length=10,max_length=1000)
    confirmed: Literal[True]

    @model_validator(mode='after')
    def source(self):
        if (self.source_key is None)==(self.value is None): raise ValueError('Choose a calculation field or a manual assumption')
        if len(self.note.strip())<10: raise ValueError('Explain the input definition, scope or assumption')
        if self.value is not None: parse_number(self.value)
        return self


class Quote(StrictModel):
    price: str=Field(max_length=80)
    currency: Literal['USD','EUR','GBP','RUB']
    date: date
    instrument: str=Field(min_length=3,max_length=160)
    kind: Literal['ordinary_share']
    source: str=Field(min_length=10,max_length=500)

    @model_validator(mode='after')
    def positive(self):
        if parse_number(self.price)<=0: raise ValueError('Quote price must be positive')
        if len(self.instrument.strip())<3 or len(self.source.strip())<10: raise ValueError('Identify the ordinary share and quote source')
        return self


class ValuationInput(StrictModel):
    calculation_id: str=Field(min_length=1,max_length=32)
    title: str=Field(min_length=1,max_length=160)
    method: Literal['ddm','fcfe','pe','pb']
    currency: Literal['USD','EUR','GBP','RUB']
    valuation_date: date
    reference_year: int=Field(ge=1900,le=2200)
    method_note: str=Field(min_length=20,max_length=2000)
    scope_note: str=Field(min_length=20,max_length=2000)
    shares_note: str=Field(min_length=20,max_length=2000)
    method_confirmed: Literal[True]
    capital_confirmed: bool=False
    comparability_confirmed: bool=False
    quote: Quote | None=None
    operating: bool=False
    operating_month: str | None=Field(default=None,pattern=r'^[0-9]{4}-(0[1-9]|1[0-2])$')
    operating_note: str=Field(default='',max_length=2000)
    scenarios: dict[Literal['base','optimistic','stress'],dict[str,Binding]]=Field(min_length=1,max_length=3)

    @model_validator(mode='after')
    def method_gate(self):
        for field in ('method_note','scope_note','shares_note'):
            if len(getattr(self,field).strip())<20: raise ValueError('Explain methodology, reporting perimeter and common-share basis')
        if not self.title.strip(): raise ValueError('Title is required')
        if 'base' not in self.scenarios: raise ValueError('Base scenario is required')
        if self.method in ('ddm','fcfe'):
            if not self.capital_confirmed: raise ValueError('Confirm distributions/FCFE after regulatory capital needs')
            if self.valuation_date!=date(self.reference_year,12,31): raise ValueError('DCF v1 uses a calendar-year-end valuation date and five following annual cash flows')
        elif not self.comparability_confirmed: raise ValueError('Confirm comparable banks, accounting basis, period and multiple selection')
        if self.quote:
            if self.quote.currency!=self.currency: raise ValueError('Quote and valuation currencies must match; no FX or pence conversion')
            if self.quote.date>self.valuation_date: raise ValueError('Quote cannot postdate the valuation date')
        if self.operating and (not self.operating_month or len(self.operating_note.strip())<20):
            raise ValueError('Specify the operating month, activity event, cohort and constant-retention assumptions')
        if self.operating and date.fromisoformat(self.operating_month+'-01')>self.valuation_date:
            raise ValueError('Operating month cannot postdate the valuation date')
        if not self.operating and (self.operating_month or self.operating_note): raise ValueError('Operating metadata requires the operating module')
        return self


def receipt(row):
    return dict(id=row.id,title=row.title,company_id=row.company_id,calculation_id=row.calculation_id,
                method=row.method,policy=row.policy,state=row.state,created=row.created,input_hash=row.input_hash,result_hash=row.result_hash)


def owned_valuation(db,actor,run_id):
    row=db.scalar(select(ValuationRun).where(ValuationRun.id==run_id,ValuationRun.org_id==actor.org_id,ValuationRun.owner_id==actor.id))
    if not row: raise HTTPException(404,'Valuation not found')
    return row


def read_receipt(row):
    data,result=json.loads(row.input),json.loads(row.output)
    if checksum(data)!=row.input_hash or checksum(result)!=row.result_hash: raise HTTPException(409,'Valuation integrity check failed')
    return data,result


def source_current(db,actor,company_id,source):
    snapshot=source['input']['snapshot']
    if not snapshot: return None
    current=review_state(db,actor,company_id)
    return current['ready'] and current['state_hash']==snapshot['state_hash']


@router.post('',status_code=201)
def create(data:ValuationInput,request:Request):
    actor=authenticate(request,True);idem=request.headers.get('idempotency-key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',idem): raise HTTPException(422,'Valid Idempotency-Key required')
    request_hash=checksum(data.model_dump(mode='json'))
    with Session(request.app.state.engine) as db,db.begin():
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        old=db.scalar(select(ValuationRun).where(ValuationRun.owner_id==actor.id,ValuationRun.idem_key==idem))
        if old:
            if old.request_hash!=request_hash: raise HTTPException(409,'Idempotency key was used for another valuation')
            return receipt(old)
        if data.valuation_date>datetime.now(timezone.utc).date(): raise HTTPException(422,'Valuation date cannot be in the future')
        source_row=private_run(db,actor,data.calculation_id)
        db.scalar(select(Company).where(Company.id==source_row.company_id).with_for_update())
        source_input,source_output=verified_payload(source_row)
        source=dict(id=source_row.id,input_hash=source_row.input_hash,result_hash=source_row.result_hash,input=source_input,result=source_output)
        if source_output['state']=='blocked': raise HTTPException(409,'Resolve the blocked source calculation first')
        if source_current(db,actor,source_row.company_id,source) is False: raise HTTPException(409,'Source facts changed; create a calculation from a current verified set')
        target={f['key']:f for f in input_fields(data.method,data.currency,data.reference_year,data.operating)}
        original_fields={f['key']:f for f in source_input['template']['contract']['fields']}
        resolved={}
        for name,bindings in data.scenarios.items():
            if name not in source_output['scenarios']: raise HTTPException(422,'Scenario does not exist in the source calculation')
            if set(bindings)!=set(target): raise HTTPException(422,f'{name}: provide every method input exactly once; no extra inputs')
            resolved[name]={}
            for key,binding in bindings.items():
                entry=dict(actor_id=actor.id,confirmed=True,note=binding.note.strip())
                if binding.source_key:
                    original=original_fields.get(binding.source_key)
                    value=source_output['scenarios'][name]['values'].get(binding.source_key)
                    if not original or not value: raise HTTPException(422,'Source calculation field not found')
                    if original['unit']!=target[key]['unit'] or original['period']!=target[key]['period']:
                        raise HTTPException(422,f'{key}: source field currency/unit or period does not match')
                    entry.update(value=value['value'],source='calculation',source_key=binding.source_key,
                        source_definition=original['definition'])
                else: entry.update(value=binding.value,source='manual_assumption')
                try: bound_number(entry['value'])
                except ValueError as exc: raise HTTPException(422,str(exc)) from None
                resolved[name][key]=entry
        payload=data.model_dump(mode='json',exclude={'scenarios','calculation_id'})
        payload.update(policy=POLICY,engine=ENGINE,company_id=source_row.company_id,source=source,scenarios=resolved,
            contract=contract(data.method,data.currency,data.reference_year,data.operating),confirmed_by=actor.id,
            warnings=['Method and perimeter checked by analyst; no independent model approval.',
                      'Publication-time availability of source evidence is not verified; not a point-in-time backtest.'])
        if source_output['state']=='calculated_without_checks': payload['warnings'].append('Source calculation has no configured control checks.')
        if data.quote and (data.valuation_date-data.quote.date).days>7: payload['warnings'].append('Quote is more than seven calendar days older than the valuation date.')
        if not data.quote: payload['warnings'].append('No quote supplied; upside is unavailable.')
        result=value_scenarios(payload)
        row=ValuationRun(org_id=actor.org_id,owner_id=actor.id,company_id=source_row.company_id,
            calculation_id=source_row.id,title=data.title.strip(),method=data.method,policy=POLICY,state=result['state'],
            idem_key=idem,request_hash=request_hash,input_hash=checksum(payload),result_hash=checksum(result),
            input=canonical(payload),output=canonical(result))
        db.add(row);db.flush();audit(db,actor,'valuation.create',row.id,'method='+data.method+';state='+row.state)
        return receipt(row)


@router.get('')
def listing(request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        return [receipt(row) for row in db.scalars(select(ValuationRun).where(ValuationRun.org_id==actor.org_id,
            ValuationRun.owner_id==actor.id).order_by(ValuationRun.created.desc()).limit(200))]


@router.get('/{run_id}')
def detail(run_id:str,request:Request):
    actor=authenticate(request)
    with Session(request.app.state.engine) as db:
        row=owned_valuation(db,actor,run_id);data,result=read_receipt(row)
        return dict(receipt(row),input=data,result=result,inputs_current=source_current(db,actor,row.company_id,data['source']))


@router.post('/{run_id}/replay')
def replay(run_id:str,request:Request):
    actor=authenticate(request,True)
    with Session(request.app.state.engine) as db,db.begin():
        row=owned_valuation(db,actor,run_id);data,_=read_receipt(row)
        if row.policy!=POLICY or data['engine']!=ENGINE: raise HTTPException(409,'Original valuation policy and calculator version required')
        matched=checksum(value_scenarios(data))==row.result_hash
        if not matched: raise HTTPException(409,'Valuation replay does not match the saved result')
        audit(db,actor,'valuation.replay',row.id,'matched=True')
        return dict(id=row.id,matched=True,result_hash=row.result_hash)

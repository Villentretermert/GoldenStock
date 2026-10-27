"""Normalization contracts are deterministic; no claim of financial model accuracy."""
import json
from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session
from goldenstock.normalization import FactInput, normalize, number, conflicts
from goldenstock.models import Extraction
from tests.test_workspace import workspace, upload


def context(**changes):
    values=dict(job_id='a'*32,item_index=0,number_text='2',metric='profit',unit='money',scale='millions',
        currency='USD',period_kind='year',period_start='2025-01-01',period_end='2025-12-31',scope='group',
        scope_detail='Consolidated group',accounting='IFRS',definition='Total profit after tax',disclosure='original')
    return values|changes


def normalized(id='a',**changes):
    data=FactInput(**context(**changes))
    return dict(normalize(data,dict(text=data.number_text,location={'page':1},method='native')),id=id)


@pytest.mark.parametrize('raw,unit,scale,expected',[
    ('(1,234.50)','money','thousands','-1234500.00'),
    ('−120','money','units','-120'),('12.5%','percent','units','0.125'),
    ('(12.5%)','percent','units','-0.125'),('125','bps','units','0.0125'),
    ('0','money','millions','0')])
def test_numbers(raw,unit,scale,expected):
    assert Decimal(number(raw,unit,scale))==Decimal(expected)


@pytest.mark.parametrize('raw',['','—','N/A','1,23','1.000,50','NaN','Infinity','120*','1e6'])
def test_no_fabricated_or_ambiguous_numbers(raw):
    with pytest.raises(ValueError): number(raw,'money','units')


@pytest.mark.parametrize('text,selection',[('−120','120'),('( 120 )','120'),('1200','120'),('12.5%','12.5'),('2 and 2','2')])
def test_complete_unique_source_number(text,selection):
    with pytest.raises(ValueError): normalize(FactInput(**context(number_text=selection)),dict(text=text,location={},method='native'))


def test_scale_conversion_and_core_blocker():
    left=normalized()
    assert conflicts([left,normalized('b',number_text='2,000',scale='thousands')])==[]
    queue=conflicts([left,normalized('b',number_text='3')])
    assert queue[0]['severity']=='blocker'
    assert conflicts([normalized(metric='roe',unit='percent',currency='',scale='units'),
                      normalized('b',metric='roe',unit='fraction',currency='',scale='units',number_text='0.02')])==[]


@pytest.mark.parametrize('change',[
    {'currency':'RUB'},{'scope':'bank'},{'accounting':'US_GAAP'},{'definition':'Profit attributable to owners'},
    {'period_kind':'ytd'}, {'period_kind':'quarter','period_start':'2025-10-01'}])
def test_noncomparable_context_is_warning(change):
    queue=conflicts([normalized(),normalized('b',number_text='3',**change)])
    assert queue[0]['severity']=='warning' and queue[0]['kind']=='context_mismatch'


def test_incompatible_mau_and_missing_ltv():
    first=normalized(metric='mau',unit='count',currency='',scale='units',definition='Unique signed-in app users')
    other=normalized('b',metric='mau',unit='count',currency='',scale='units',definition='Unique paying users')
    assert conflicts([first,other])[0]['kind']=='context_mismatch'
    with pytest.raises(ValidationError): FactInput(**context(metric='roe'))
    with pytest.raises(ValidationError): FactInput(**context(period_end='2024-01-01'))
    with pytest.raises(ValidationError): FactInput(**context(metric='equity'))


def seed(client,app,key='normalization-test'):
    receipt=upload(client,key=key).json()
    with Session(app.state.engine) as db,db.begin():
        db.add(Extraction(version_id=receipt['version_id'],parser_version='synthetic',source_sha256=receipt['sha256'],
            payload=json.dumps({'items':[dict(text='2',location={'page':1},method='native'),
                dict(text='3',location={'page':2},method='ocr',confidence=.8)]})))
    return receipt


def test_fact_history_conflicts_privacy_and_missing_metrics(workspace):
    app,connect=workspace; a,b,e=connect(),connect('bob'),connect('eve')
    receipt=seed(a,app); data=context(job_id=receipt['job_id'])
    first=a.post('/api/v1/facts',json=data)
    assert first.status_code==201,first.text
    fid=first.json()['id']
    assert a.post('/api/v1/facts',json=data).json()['id']==fid
    second=a.post('/api/v1/facts',json=data|{'item_index':1,'number_text':'3'}).json()
    queue=a.get('/api/v1/conflicts?company_id=sber').json()
    assert queue['blocker_count']==1 and 'ltv' in queue['missing_metrics']
    assert second['warnings']==['ocr_requires_review']
    for client in (b,e):
        assert client.get('/api/v1/facts/'+fid).status_code==404
        assert client.get('/api/v1/facts?company_id=sber').json()==[]
        assert client.get('/api/v1/conflicts?company_id=sber').json()['blocker_count']==0
        assert client.post('/api/v1/facts',json=data).status_code==404
    corrected=a.post('/api/v1/facts',json=data|{'supersedes':second['id']}).json()
    assert corrected['id']!=second['id']
    assert a.get('/api/v1/conflicts?company_id=sber').json()['blocker_count']==0
    assert len(a.get('/api/v1/facts?company_id=sber&history=true').json())==3
    assert a.get('/api/v1/facts/'+second['id']).json()['value']=='3000000'
    assert a.post('/api/v1/facts',json=data|{'supersedes':second['id'],'disclosure':'restated'}).status_code==409
    assert a.patch('/api/v1/facts/'+fid,json={'value':'0'}).status_code==405


def test_mapping_rejects_missing_and_fake_evidence(workspace):
    app,connect=workspace; client=connect(); receipt=seed(client,app)
    data=context(job_id=receipt['job_id'])
    for change in [{'number_text':'999'},{'item_index':20},{'value':'123'},{'currency':'XYZ'}]:
        assert client.post('/api/v1/facts',json=data|change).status_code==422
    assert client.post('/api/v1/facts',headers={'x-csrf-token':'bad'},json=data).status_code==403
    assert client.post('/api/v1/facts',json=data|{'supersedes':'other'}).status_code==404


def test_facts_ui_escapes_definition(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace;mount_ui(app);client=connect();receipt=seed(client,app)
    response=client.post('/api/v1/facts',json=context(job_id=receipt['job_id'],definition='<script>alert(1)</script>'))
    assert response.status_code==201
    html=client.get('/facts/sber').text
    assert '&lt;script&gt;' in html and '<script>alert(1)</script>' not in html
    assert client.get('/normalize/'+receipt['job_id']+'/0').status_code==200

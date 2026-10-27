"""Known-answer arithmetic, immutable provenance and calculation access gates."""
import copy
import io
from decimal import Decimal, localcontext
import pytest
from openpyxl import load_workbook
from sqlalchemy.orm import Session
from test_workspace import workspace
from test_templates import DEMO,post,modify
from test_normalization import seed
from test_reviews import fact,decide,save
from goldenstock.calculation_engine import calculate,parse_formula,evaluate,parse_number
from goldenstock.template_contract import validate_template
from goldenstock.models import CalculationRun


def binding(value): return dict(value=value,note='Explicit synthetic assumption',confirmed=True)


def payload(version):
    return dict(title='Synthetic scenarios',company_id='sber',template_id=version['template_id'],version_id=version['id'],
        scenarios={'base':{'profit_owners':binding('100'),'growth':binding('0.05')}},checks=[])


def run(client,data,key='calculation-test-001'):
    return client.post('/api/v1/calculations',json=data,headers={'Idempotency-Key':key})


def test_synthetic_workbook_known_answers_and_zero_growth():
    contract=validate_template(DEMO)
    inputs={'base':{'profit_owners':binding('100'),'growth':binding('0.05')},
            'stress':{'profit_owners':binding('100'),'growth':binding('0')}}
    result=calculate(contract,inputs,[])
    outputs=[f for f in contract['fields'] if f['role']=='output']
    expected=['105','110.25','115.7625','121.550625','127.62815625']
    book=load_workbook(io.BytesIO(DEMO),data_only=True)
    for f,value in zip(outputs,expected):
        assert result['scenarios']['base']['values'][f['key']]['value']==value
        # Independently recalculated and cached by Artifact Tool in GS-017.
        assert abs(Decimal(str(book['Model'][f['cell']].value))-Decimal(value))<Decimal('0.000000001')
        assert result['scenarios']['stress']['values'][f['key']]['value']=='100'
    assert result['state']=='calculated_without_checks'


@pytest.mark.parametrize('formula,expected',[
    ('=-A1^A3','4'),('=A1^A2^A3','64'),('=A1^(A2^A3)','512'),
    ('=A1/A3*A2','3'),('=1+A1*A2','7'),('=(1+A1)*A2','9'),
    ("='Model'!$A$1+Model!A2",'5'),('=A1^-A3','0.25'),('=1--A1','3'),
])
def test_excel_operator_precedence(formula,expected):
    tree,refs=parse_formula(formula)
    assert evaluate(tree,{'A1':Decimal(2),'A2':Decimal(3),'A3':Decimal(2)})==Decimal(expected)


@pytest.mark.parametrize('formula',['=1//1','=1**1','=A1 A2','=Model!Model!A1','=SUM(A1)','=1e1','=True','=__import__(1)'])
def test_unsupported_expressions_rejected(formula):
    with pytest.raises(ValueError): parse_formula(formula)


@pytest.mark.parametrize('value',['','NaN','Infinity','1e20','1,000',1.25,'0.'+'0'*18+'1','1'+'0'*31])
def test_numeric_input_limits(value):
    with pytest.raises(ValueError): parse_number(value)


def single_formula(formula):
    return dict(order=['A1','A2','A3'],fields=[
        dict(key='left',cell='A1',role='input',unit='USD'),dict(key='right',cell='A2',role='input',unit='ratio'),
        dict(key='result',cell='A3',role='output',unit='USD',formula=formula)])


def test_rounding_checks_and_unbalanced_residual():
    contract=single_formula('=A1+A2')
    scenarios={'base':{'left':binding('1.005'),'right':binding('0')}}
    check=dict(key='result',expected='1',tolerance='0.005',note='Source rounding allowance')
    result=calculate(contract,scenarios,[check])
    assert result['state']=='checks_passed'
    assert result['scenarios']['base']['values']['result']==dict(value='1.005',display='1.01')
    check['tolerance']='0.004'
    assert calculate(contract,scenarios,[check])['state']=='blocked'
    balance=single_formula('=A1-A2')
    inputs={'base':{'left':binding('100'),'right':binding('99')}}
    assert calculate(balance,inputs,[dict(key='result',expected='0',tolerance='0',note='Assets less liabilities and equity')])['state']=='blocked'
    with localcontext() as ctx:
        ctx.prec=3
        # Calculation context must not depend on the caller's decimal precision.
        assert calculate(contract,scenarios,[])['scenarios']['base']['values']['result']['value']=='1.005'


@pytest.mark.parametrize('formula,left,right,error',[
    ('=A1/A2','1','0','division_by_zero'),('=A1^A2','0','0','undefined_zero_power'),
    ('=A1^A2','2','0.5','exponent_must_be_integer_between_minus_1000_and_1000'),
    ('=A1^A2','2','1001','exponent_must_be_integer_between_minus_1000_and_1000'),
    ('=A1^A2','1000000000000000000000000000000','1000','numeric_range_or_domain_error'),
])
def test_explicit_numeric_failures(formula,left,right,error):
    result=calculate(single_formula(formula),{'base':{'left':binding(left),'right':binding(right)}},[])
    assert result['state']=='blocked'
    assert result['scenarios']['base']['error']['code']==error


def test_api_scenarios_idempotency_privacy_replay_and_tamper(workspace):
    app,connect=workspace;a,b,e=connect(),connect('bob'),connect('eve')
    version=post(a).json();data=payload(version)
    data['scenarios']['optimistic']={'profit_owners':binding('100'),'growth':binding('0.1')}
    data['scenarios']['stress']={'profit_owners':binding('100'),'growth':binding('-0.05')}
    response=run(a,data);assert response.status_code==201,response.text
    rid=response.json()['id'];url='/api/v1/calculations/'+rid
    assert run(a,data).json()['id']==rid
    changed=copy.deepcopy(data);changed['title']='Changed'
    assert run(a,changed).status_code==409
    detail=a.get(url).json()
    assert len(detail['result']['scenarios'])==3
    assert detail['input']['template']['version_id']==version['id']
    assert a.post(url+'/replay').json()['matched']
    for other in (b,e):
        assert other.get(url).status_code==404
        assert other.post(url+'/replay').status_code==404
        assert other.get('/api/v1/calculations').json()==[]
        assert run(other,data).status_code==404
    # Sharing structure does not share calculations or require hidden original values.
    assert a.patch('/api/v1/templates/'+version['template_id']+'/visibility',json=dict(shared=True,revision=1)).status_code==200
    other=run(b,data).json()
    assert a.get('/api/v1/calculations/'+other['id']).status_code==404
    assert a.patch('/api/v1/templates/'+version['template_id']+'/visibility',json=dict(shared=False,revision=2)).status_code==200
    assert b.post('/api/v1/calculations/'+other['id']+'/replay').json()['matched']
    assert post(a,template_id=version['template_id'],key='new-template-version').status_code==201
    assert a.get(url).json()==detail
    assert a.post(url+'/replay',headers={'x-csrf-token':'bad'}).status_code==403
    with Session(app.state.engine) as db,db.begin(): db.get(CalculationRun,rid).output='{}'
    assert a.get(url).status_code==409
    assert a.post(url+'/replay').status_code==409


def test_missing_unknown_unconfirmed_and_failed_checks(workspace):
    app,connect=workspace;a=connect();version=post(a).json();data=payload(version)
    bad=copy.deepcopy(data);del bad['scenarios']['base']['growth']
    assert run(a,bad).status_code==422
    bad=copy.deepcopy(data);bad['scenarios']['base']['extra']=binding('1')
    assert run(a,bad).status_code==422
    bad=copy.deepcopy(data);bad['scenarios']['base']['growth']['confirmed']=False
    assert run(a,bad).status_code==422
    bad=copy.deepcopy(data);bad['scenarios']['base']['growth']['fact_id']='unknown'
    assert run(a,bad).status_code==422
    bad=copy.deepcopy(data);bad['checks']=[dict(key='growth',expected='0',tolerance='0',note='Cannot check an input')]
    assert run(a,bad).status_code==422
    field=next(f['key'] for f in version['contract']['fields'] if f['role']=='output')
    data['checks']=[dict(key=field,expected='0',tolerance='0',note='Deliberately failing check')]
    result=run(a,data);assert result.status_code==201,result.text
    assert result.json()['state']=='blocked'
    assert a.post('/api/v1/calculations/'+result.json()['id']+'/replay').json()['matched']


def test_verified_facts_stale_gate_and_period_currency(workspace):
    app,connect=workspace;a=connect();receipt=seed(a,app)
    fid=fact(a,receipt,currency='USD',period_start='2025-01-01',period_end='2025-12-31')
    assert decide(a,fid).status_code==201
    sid=save(a).json()['id'];version=post(a).json();data=payload(version)
    data['snapshot_id']=sid
    data['scenarios']['base']['profit_owners']=dict(fact_id=fid,note='Verified mapping to synthetic profit; definition and perimeter checked',confirmed=True)
    response=run(a,data);assert response.status_code==201,response.text
    rid=response.json()['id'];original=a.get('/api/v1/calculations/'+rid).json()
    assert original['inputs_current'] is True
    assert original['input']['scenarios']['base']['profit_owners']['fact']['id']==fid
    mismatch=post(a,modify(lambda b:setattr(b['GS_Map']['D2'],'value','EUR')),key='mismatch-template').json()
    bad=data|dict(template_id=mismatch['template_id'],version_id=mismatch['id'])
    assert run(a,bad,'mismatch-currency').status_code==422
    assert decide(a,fid,'unreviewed',1).status_code==201
    assert run(a,data,'new-stale-attempt').status_code==409
    assert run(a,data).json()['id']==rid  # Existing receipt remains historical.
    assert a.get('/api/v1/calculations/'+rid).json()['inputs_current'] is False
    assert a.post('/api/v1/calculations/'+rid+'/replay').json()['matched']


def test_calculation_pages_and_escaping(workspace):
    app,connect=workspace
    from goldenstock.ui import mount_ui
    mount_ui(app);a=connect();version=post(a).json();data=payload(version);data['title']='<script>bad()</script>'
    url='/calculations/new?template_id='+version['template_id']+'&version_id='+version['id']
    page=a.get(url);assert page.status_code==200,page.text
    assert 'Calculate and save private scenarios' in page.text
    rid=run(a,data).json()['id'];page=a.get('/calculations/'+rid)
    assert '&lt;script&gt;' in page.text and '<script>bad()' not in page.text
    assert '127.63' in page.text and 'No control checks were configured' in page.text
    assert 'Verify reproducibility' in page.text

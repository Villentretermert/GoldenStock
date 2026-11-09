"""Scenario bounds use exact saved outcomes and retain historical/private semantics."""
from copy import deepcopy
from decimal import Decimal,localcontext
import pytest
from sqlalchemy.orm import Session
from test_workspace import workspace
from test_templates import post
from test_calculations import payload as calc_payload,run as calculate
from test_valuations import engine_payload,binding,api_payload,create,source
from test_reviews import decide
from goldenstock.valuation_engine import value_scenarios
from goldenstock.valuation_summary import summarize
from goldenstock.models import ValuationRun
from goldenstock.calculation_engine import canonical,checksum


def cases(method='pe'):
    payload=engine_payload(method)|dict(currency='USD',reference_year=2025)
    for name,factor in [('stress',Decimal('.5')),('optimistic',Decimal('1.5'))]:
        values=deepcopy(payload['scenarios']['base'])
        keys=['multiple'] if method in ('pe','pb') else [f'cash_{n}' for n in range(1,6)]
        for key in keys: values[key]=binding(Decimal(values[key]['value'])*factor)
        payload['scenarios'][name]=values
    return payload


@pytest.mark.parametrize('method,low,base,high',[('pe','45','90','135'),('pb','60','120','180'),
    ('ddm','50','100','150'),('fcfe','50','100','150')])
def test_four_methods_use_only_declared_scenarios(method,low,base,high):
    payload=cases(method);result=value_scenarios(payload);before=deepcopy(result)
    summary=summarize(payload,result,None)
    assert summary['status']=='range' and summary['method']==method and summary['scenario_count']==3
    for key,expected in [('low',low),('base',base),('high',high)]:
        assert summary['metrics']['per_share'][key]['display']==f'{Decimal(expected):.2f}'
        assert Decimal(summary['metrics']['equity_value'][key]['value'])==Decimal(expected)*10
    assert summary['metrics']['per_share']['low']['scenarios']==['stress']
    assert summary['metrics']['per_share']['high']['scenarios']==['optimistic']
    assert result==before
    # Extreme sensitivity points and display strings never set scenario bounds.
    for scenario in result['scenarios'].values():
        scenario['sensitivity']=[dict(per_share=dict(value='999999999',display='999999999'))]
        scenario['values']['per_share']['display']='misleading cached display'
    assert summarize(payload,result,None)==summary
    with localcontext() as ctx:
        ctx.prec=4
        assert summarize(payload,result,None)==summary


def test_share_and_equity_extremes_can_come_from_different_scenarios():
    payload=cases();payload['scenarios']['stress']['shares']=binding(1)
    payload['scenarios']['optimistic']['shares']=binding(30)
    summary=summarize(payload,value_scenarios(payload),True)
    assert summary['metrics']['per_share']['high']['scenarios']==['stress']
    assert summary['metrics']['equity_value']['high']['scenarios']==['optimistic']
    assert summary['metrics']['per_share']['high']['value']=='450'
    assert summary['metrics']['equity_value']['high']['value']=='1350'


def test_single_ties_rounding_and_small_positive_outcomes():
    payload=cases();result=value_scenarios(payload)
    for scenario in result['scenarios'].values(): scenario['values']['per_share']['value']='1.0041'
    tied=summarize(payload,result,None)['metrics']['per_share']
    assert tied['same_value'] and len(tied['low']['scenarios'])==3
    result['scenarios']['stress']['values']['per_share']['value']='1.0042'
    rounded=summarize(payload,result,None)['metrics']['per_share']
    assert not rounded['same_value'] and rounded['same_display'] and rounded['high']['value']=='1.0042'
    for scenario in result['scenarios'].values(): scenario['values']['per_share']['value']='0.000001'
    assert summarize(payload,result,None)['metrics']['per_share']['low']['display']=='<0.01'
    payload['scenarios']={'base':payload['scenarios']['base']};result['scenarios']={'base':result['scenarios']['base']}
    assert summarize(payload,result,None)['status']=='single'
    result['scenarios']['base']['values']['equity_value']['value']='1'+'0'*60
    huge=summarize(payload,result,None)['metrics']['equity_value']['base']
    assert huge['value']=='1'+'0'*60 and huge['display'].replace(',','')=='1'+'0'*60+'.00'


@pytest.mark.parametrize('bad',['NaN','Infinity','-1','0',1.0,'1e500',None])
def test_invalid_outcome_does_not_produce_a_partial_range(bad):
    payload=cases();result=value_scenarios(payload)
    result['scenarios']['stress']['values']['per_share']['value']=bad
    summary=summarize(payload,result,None)
    assert summary['status']=='unavailable' and summary['metrics']=={}


def test_missing_extra_and_blocked_scenarios_do_not_produce_partial_range():
    payload=cases();result=value_scenarios(payload)
    variants=[]
    missing=deepcopy(result);del missing['scenarios']['stress'];variants.append(missing)
    extra=deepcopy(result);extra['scenarios']['unknown']=extra['scenarios']['base'];variants.append(extra)
    malformed=deepcopy(result);malformed['scenarios']['stress']=None;variants.append(malformed)
    absent=deepcopy(result);del absent['scenarios']['base']['values']['equity_value'];variants.append(absent)
    blocked=deepcopy(result);blocked['state']='blocked';blocked['scenarios']['stress']=dict(state='blocked',values={},errors=['invalid_inputs']);variants.append(blocked)
    for saved in variants:
        assert summarize(payload,saved,None)['status']=='unavailable'
        assert summarize(payload,saved,None)['metrics']=={}
    assert summarize(payload|dict(scenarios={}),result,None)['status']=='unavailable'


def multi_source(client):
    version=post(client).json();data=calc_payload(version)
    for name in ('stress','optimistic'): data['scenarios'][name]=deepcopy(data['scenarios']['base'])
    response=calculate(client,data);assert response.status_code==201,response.text
    return response.json()['id']


def test_api_ui_range_first_privacy_and_unchanged_receipt(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace;mount_ui(app);a=connect();b=connect('bob');e=connect('eve')
    cid=multi_source(a);data=api_payload(cid);data['scenarios']=cases()['scenarios']
    data['method_note']='<script>alert("synthetic")</script>'
    rid=create(a,data).json()['id'];url='/api/v1/valuations/'+rid
    with Session(app.state.engine) as db:
        row=db.get(ValuationRun,rid);original=(row.input,row.output,row.input_hash,row.result_hash)
    detail=a.get(url).json();assert detail['scenario_summary']['metrics']['per_share']['low']['value']=='45'
    page=a.get('/valuations/'+rid);assert page.status_code==200,page.text
    html=page.text
    assert html.index('Scenario valuation range')<html.index('Download this valuation')<html.index('Base</h2>')
    assert '45.00 – 135.00' in html and '450.00 – 1,350.00' in html and 'USD / share' in html
    assert 'Manual assumptions: no verified fact snapshot.' in html
    assert 'Exact bounds and scenario assumptions' in html and '<script>alert(' not in html
    assert a.post(url+'/replay').json()['matched']
    for other in (b,e):
        assert other.get(url).status_code==404 and other.get('/valuations/'+rid).status_code==404
    with Session(app.state.engine) as db:
        row=db.get(ValuationRun,rid);assert (row.input,row.output,row.input_hash,row.result_hash)==original


def test_historical_status_keeps_original_bounds_and_single_is_explicit(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace;mount_ui(app);a=connect();cid,fid=source(a,app,verified=True)
    rid=create(a,api_payload(cid)).json()['id'];url='/api/v1/valuations/'+rid
    before=a.get(url).json()['scenario_summary']
    assert before['status']=='single' and before['review_status']=='reviewed_snapshot'
    assert 'Single scenario — range unavailable.' in a.get('/valuations/'+rid).text
    decide(a,fid,'unreviewed',1).raise_for_status()
    after=a.get(url).json()['scenario_summary']
    assert after['review_status']=='historical' and after['metrics']==before['metrics']
    assert 'Historical result: source review changed.' in a.get('/valuations/'+rid).text
    assert a.post(url+'/replay').json()['matched']


def test_blocked_and_incomplete_saved_sets_are_explicit_in_ui(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace;mount_ui(app);a=connect();cid=multi_source(a)
    data=api_payload(cid);data['scenarios']=cases()['scenarios'];data['scenarios']['stress']['shares']=binding(0)
    rid=create(a,data).json()['id'];url='/valuations/'+rid
    html=a.get(url).text
    assert 'Range unavailable.' in html and 'Blocked:' in html and 'Download this valuation' not in html
    # A retained older receipt with an incomplete set must render an explicit gap.
    import json
    with Session(app.state.engine) as db,db.begin():
        row=db.get(ValuationRun,rid);result=json.loads(row.output);result['state']='calculated';del result['scenarios']['stress']
        row.output=canonical(result);row.result_hash=checksum(result);row.state='calculated'
    response=a.get(url);assert response.status_code==200,response.text
    assert 'Missing or incomplete saved result' in response.text and 'Range unavailable.' in response.text

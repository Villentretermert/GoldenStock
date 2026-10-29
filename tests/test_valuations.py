"""Independent known answers, financial scope checks and immutable valuation access."""
import copy
from decimal import Decimal, localcontext
import pytest
from sqlalchemy.orm import Session
from test_workspace import workspace
from test_templates import post
from test_calculations import payload as calculation_payload,run as calculate
from test_normalization import seed
from test_reviews import fact,decide,save
from goldenstock.models import ValuationRun
from goldenstock.valuation_engine import contract,value_scenarios


def binding(value): return dict(value=str(value),note='Synthetic explicit assumption',confirmed=True)


def numbers(method='pe',operating=False):
    values={'shares':'10'}
    if method in ('ddm','fcfe'): values.update({f'cash_{n}':'100' for n in range(1,6)}|dict(cost_equity='0.1',terminal_growth='0'))
    elif method=='pe': values.update(profit_owners='100',preferred_dividends='10',multiple='10')
    else: values.update(equity_total='1000',equity_nci='100',equity_preferred='100',multiple='1.5')
    if operating: values.update(monthly_revenue='1000',mau='100',cohort_start='100',cohort_retained='80',contribution_margin='0.5',monthly_discount='0.1')
    return {k:binding(v) for k,v in values.items()}


def engine_payload(method='pe',operating=False):
    return dict(method=method,operating=operating,contract=contract(method,'USD',2025,operating),quote=None,scenarios={'base':numbers(method,operating)})


@pytest.mark.parametrize('method,expected',[('ddm','100'),('fcfe','100'),('pe','90'),('pb','120')])
def test_known_equity_valuations(method,expected):
    result=value_scenarios(engine_payload(method));scenario=result['scenarios']['base']
    assert result['state']=='calculated'
    assert abs(Decimal(scenario['values']['per_share']['value'])-Decimal(expected))<Decimal('1e-25')
    assert len(scenario['sensitivity'])==(9 if method in ('ddm','fcfe') else 3)
    if method in ('ddm','fcfe'):
        grid=scenario['sensitivity']
        assert Decimal(grid[1]['per_share']['value'])>Decimal(grid[4]['per_share']['value'])>Decimal(grid[7]['per_share']['value'])
        assert Decimal(grid[3]['per_share']['value'])<Decimal(grid[4]['per_share']['value'])<Decimal(grid[5]['per_share']['value'])
    else:
        assert [p['per_share']['display'] for p in scenario['sensitivity']]==(['72.00','90.00','108.00'] if method=='pe' else ['96.00','120.00','144.00'])


def test_cohort_metrics_timing_and_not_enterprise_value():
    result=value_scenarios(engine_payload('pe',True))['scenarios']['base']['values']
    assert result['arpu_monthly']['value']=='10'
    assert result['retention_monthly']['value']=='0.8'
    assert result['lifetime_months']['value']=='5'
    assert result['ltv_contribution']['display']=='16.67'
    assert result['per_share']['value']=='90'  # User economics do not become bank equity.
    plain=value_scenarios(engine_payload())['scenarios']['base']['values']
    assert 'ltv_contribution' not in plain


@pytest.mark.parametrize('method,key,value',[
    ('ddm','cost_equity','0'),('ddm','terminal_growth','0.1'),('ddm','terminal_growth','-1'),
    ('ddm','cash_1','-10'),('fcfe','cash_5','0'),('pe','preferred_dividends','100'),
    ('pe','profit_owners','-1'),('pb','equity_nci','900'),('pb','equity_preferred','-1'),
    ('pe','shares','0'),('pe','multiple','-1'),('pe','cohort_retained','100'),
    ('pe','mau','0'),('pe','cohort_start','0'),('pe','cohort_retained','0.5'),
    ('pe','contribution_margin','1.1'),('pe','monthly_discount','-0.1'),
])
def test_financial_domain_errors_block_without_partial_prices(method,key,value):
    payload=engine_payload(method,True);payload['scenarios']['base'][key]=binding(value)
    result=value_scenarios(payload)
    assert result['state']=='blocked'
    assert result['scenarios']['base']['values']=={}


def test_fcfe_negative_interim_cash_and_invalid_sensitivity_points():
    data=engine_payload('fcfe');data['scenarios']['base']['cash_1']=binding('-10')
    assert value_scenarios(data)['state']=='calculated'
    data=engine_payload('ddm');data['scenarios']['base']['cost_equity']=binding('0.005')
    result=value_scenarios(data)
    assert result['state']=='calculated'
    assert any(p['state']=='blocked' and p['per_share'] is None for p in result['scenarios']['base']['sensitivity'])
    with localcontext() as ctx:
        ctx.prec=4
        assert value_scenarios(data)==result


def source(client,app,verified=False):
    version=post(client).json();data=calculation_payload(version)
    fid=None
    if verified:
        fid=fact(client,seed(client,app));assert decide(client,fid).status_code==201
        data['snapshot_id']=save(client).json()['id']
        data['scenarios']['base']['profit_owners']=dict(fact_id=fid,note='Checked common profit source',confirmed=True)
    response=calculate(client,data);assert response.status_code==201,response.text
    return response.json()['id'],fid


def api_payload(calculation_id,method='pe'):
    return dict(calculation_id=calculation_id,title='Synthetic equity valuation',method=method,currency='USD',
        valuation_date='2025-12-31',reference_year=2025,method_note='Synthetic comparable selection or capital distribution policy',
        scope_note='Consolidated parent common equity, no NCI in the market numerator',
        shares_note='One ordinary economic common share, no ADR or currency conversion',
        method_confirmed=True,capital_confirmed=True,comparability_confirmed=True,scenarios={'base':numbers(method)})


def create(client,data,key='valuation-test-001'):
    return client.post('/api/v1/valuations',json=data,headers={'Idempotency-Key':key})


def test_valuation_acl_idempotency_sources_and_integrity(workspace):
    app,connect=workspace;a,b,e=connect(),connect('bob'),connect('eve');cid,_=source(a,app)
    data=api_payload(cid);data['scenarios']['base']['profit_owners']=dict(source_key='profit_owners',note='Parent profit definition checked against source',confirmed=True)
    response=create(a,data);assert response.status_code==201,response.text
    rid=response.json()['id'];url='/api/v1/valuations/'+rid
    assert create(a,data).json()['id']==rid
    assert create(a,data|dict(title='Changed')).status_code==409
    record=a.get(url).json()
    assert a.get('/api/v1/companies/sber').json()['latest_valuation']['id']==rid
    assert next(c for c in a.get('/api/v1/companies').json() if c['id']=='sber')['latest_calculation']['id']==cid
    assert record['input']['scenarios']['base']['profit_owners']['source']=='calculation'
    assert a.post(url+'/replay').json()['matched']
    for other in (b,e):
        assert create(other,data).status_code==404
        assert other.get(url).status_code==404 and other.post(url+'/replay').status_code==404
        assert other.get('/api/v1/valuations').json()==[]
        assert other.get('/api/v1/companies/sber').json()['latest_valuation'] is None
        assert other.get('/api/v1/companies/sber').json()['last_calculation']=='not_run'
    assert a.post(url+'/replay',headers={'x-csrf-token':'bad'}).status_code==403
    assert create(a,data|dict(currency='EUR'),'wrong-currency').status_code==422
    assert create(a,data|dict(reference_year=2024),'wrong-period').status_code==422
    with Session(app.state.engine) as db,db.begin(): db.get(ValuationRun,rid).output='{}'
    assert a.get(url).status_code==409 and a.post(url+'/replay').status_code==409


def test_quote_dates_method_confirmations_missing_and_operating_gate(workspace):
    app,connect=workspace;a=connect();cid,_=source(a,app);data=api_payload(cid)
    quote=dict(price='60',currency='USD',date='2025-12-31',instrument='Synthetic ordinary share',kind='ordinary_share',source='Synthetic price fixture only')
    data['quote']=quote
    saved=create(a,data);assert saved.status_code==201,saved.text
    result=a.get('/api/v1/valuations/'+saved.json()['id']).json()
    assert result['result']['scenarios']['base']['upside']=='0.5'
    for change in (dict(currency='EUR'),dict(date='2026-01-01'),dict(price='0'),dict(kind='adr')):
        assert create(a,data|dict(quote=quote|change),'invalid-quote').status_code==422
    old=create(a,data|dict(quote=quote|dict(date='2025-12-01')),'old-quote').json()
    assert any('seven' in x for x in a.get('/api/v1/valuations/'+old['id']).json()['input']['warnings'])
    for change in (dict(method_confirmed=False),dict(comparability_confirmed=False),dict(operating=True),dict(valuation_date='2200-12-31')):
        assert create(a,data|change,'invalid-method').status_code==422
    missing=copy.deepcopy(data);del missing['scenarios']['base']['preferred_dividends']
    assert create(a,missing,'missing-input').status_code==422
    dcf=api_payload(cid,'ddm');dcf['valuation_date']='2025-06-30'
    assert create(a,dcf,'midyear-DCF').status_code==422
    operating=api_payload(cid)|dict(operating=True,operating_month='2025-12',operating_note='Same monthly user activity and contribution perimeter; constant retention',scenarios={'base':numbers('pe',True)})
    assert create(a,operating,'operating-case').status_code==201
    for month in ('0000-01','2026-01'):
        assert create(a,operating|dict(operating_month=month),'invalid-month').status_code==422


def test_stale_source_blocks_new_valuation_but_historical_replay_remains(workspace):
    app,connect=workspace;a=connect();cid,fid=source(a,app,True);data=api_payload(cid)
    saved=create(a,data);assert saved.status_code==201,saved.text
    rid=saved.json()['id'];assert a.get('/api/v1/valuations/'+rid).json()['inputs_current'] is True
    assert decide(a,fid,'unreviewed',1).status_code==201
    assert create(a,data,'new-stale-valuation').status_code==409
    assert a.get('/api/v1/valuations/'+rid).json()['inputs_current'] is False
    assert create(a,data).json()['id']==rid
    assert a.post('/api/v1/valuations/'+rid+'/replay').json()['matched']


def test_valuation_ui_and_html_escaping(workspace):
    app,connect=workspace
    from goldenstock.ui import mount_ui
    mount_ui(app);a=connect();cid,_=source(a,app)
    assert 'Value this calculation' in a.get('/calculations/'+cid).text
    for method in ('pe','pb','ddm','fcfe'):
        page=a.get('/valuations/new',params=dict(calculation_id=cid,method=method,operating='true'))
        assert page.status_code==200,page.text
        assert 'Calculate and save equity valuation' in page.text
    data=api_payload(cid,'ddm');data['method_note']='<script>alert("synthetic")</script>'
    rid=create(a,data).json()['id'];page=a.get('/valuations/'+rid)
    assert page.status_code==200,page.text
    assert '&lt;script&gt;' in page.text and '<script>alert(' not in page.text
    assert '100.00 USD' in page.text and 'Terminal contribution' in page.text
    assert 'Verify valuation reproducibility' in page.text


def test_blocked_source_and_api_csrf(workspace):
    app,connect=workspace;a=connect();version=post(a).json();calculation=calculation_payload(version)
    calculation['checks']=[dict(key='profit_2026',expected='0',tolerance='0',note='Deliberately failing control')]
    cid=calculate(a,calculation).json()['id']
    assert create(a,api_payload(cid)).status_code==409
    a.headers['x-csrf-token']='bad'
    assert create(a,api_payload(cid)).status_code==403

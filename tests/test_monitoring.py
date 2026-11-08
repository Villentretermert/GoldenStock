"""Reporting changes, tenant isolation, idempotent delivery and safe recovery."""
import json
import time
from datetime import datetime,timezone
from decimal import Decimal
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from test_workspace import workspace
from goldenstock.models import MonitorSource,MonitorSnapshot,MonitorObservation,MonitorEvent,SiteNotification,User
from goldenstock.monitoring import process_monitor,INTERVAL
from goldenstock.monitor_index import index,number
from goldenstock.public_sources import fetch

NOW=datetime(2026,11,1,tzinfo=timezone.utc).timestamp()
ACC='0000019617-26-000001'


def filing(acc=ACC,form='10-K',filed='2026-02-01',report='2025-12-31'):
    return dict(accessionNumber=acc,form=form,filingDate=filed,reportDate=report,primaryDocument='report.htm',items='')


def submissions(*rows):
    return dict(cik=19617,filings={'recent':{key:[r[key] for r in rows] for key in filing()}})


def facts(value=100,acc=ACC,filed='2026-02-01',unit='USD',end='2025-12-31'):
    return dict(cik=19617,facts={'us-gaap':{'Assets':{'units':{unit:[dict(val=value,accn=acc,filed=filed,end=end,form='10-K')]}}}})


def setup(client,app,kind='submissions'):
    assert client.put('/api/v1/favorites/jpm').status_code==200
    with Session(app.state.engine) as db,db.begin():
        for s in db.scalars(select(MonitorSource)): s.next_check=NOW+100*INTERVAL
        db.get(MonitorSource,'jpm-'+kind).next_check=0


def tick(app,kind,data,now=NOW):
    with Session(app.state.engine) as db,db.begin(): db.get(MonitorSource,'jpm-'+kind).next_check=0
    def fake(company,contact,kind):
        if isinstance(data,Exception): raise data
        raw=json.dumps(data).encode()
        return 'https://data.sec.gov/synthetic',raw,data
    assert process_monitor(app.state.engine,app.state.settings,fake,now)


def items(client):
    return client.get('/api/v1/notifications').json()['items']


def test_baseline_new_amendment_dedupe_and_private_read_states(workspace):
    app,connect=workspace;a=connect();b=connect('bob');eve=connect('eve');setup(a,app)
    b.put('/api/v1/favorites/jpm')
    tick(app,'submissions',submissions(filing()))
    assert items(a)==[]
    new=filing('0000019617-26-000002','10-K/A','2026-03-01')
    tick(app,'submissions',submissions(new,filing()),NOW+INTERVAL)
    feed=items(a);assert len(feed)==1 and feed[0]['kind']=='amended_filing'
    assert len(items(b))==1 and items(eve)==[]
    url='/api/v1/notifications/'+feed[0]['id']+'/read'
    for other in (b,eve): assert other.post(url).status_code==404
    first=a.post(url).json();assert a.post(url).json()==first
    assert a.get('/api/v1/notifications/count').json()['unread_count']==0
    assert b.get('/api/v1/notifications/count').json()['unread_count']==1
    # Array ordering and response bytes do not define a new disclosure.
    tick(app,'submissions',submissions(filing(),new),NOW+2*INTERVAL)
    assert len(items(a))==1
    snapshot=feed[0]['detail']['after_snapshot_id']
    downloaded=a.get('/api/v1/monitor-snapshots/'+snapshot+'/download')
    assert downloaded.status_code==200 and downloaded.json()['cik']==19617
    assert a.get('/api/v1/notifications?offset=-1').status_code==422


def test_revision_decimal_units_periods_and_old_response(workspace):
    app,connect=workspace;a=connect();setup(a,app,'facts')
    tick(app,'facts',facts())
    changed=facts(110,'0000019617-26-000002','2026-03-01')
    tick(app,'facts',changed,NOW+INTERVAL)
    row=items(a)[0];assert row['kind']=='possible_revision'
    assert row['detail']['before']['value']=='100' and row['detail']['after']['value']=='110'
    assert row['detail']['before_snapshot_id']!=row['detail']['after_snapshot_id']
    # Re-publishing the number in another accession is not another value change.
    tick(app,'facts',facts(110,'0000019617-26-000003','2026-04-01'),NOW+2*INTERVAL)
    tick(app,'facts',facts(),NOW+3*INTERVAL)
    assert len(items(a))==1
    with Session(app.state.engine) as db:
        stored=json.loads(db.scalar(select(MonitorObservation).where(MonitorObservation.source_id=='jpm-facts')).payload)
        assert stored['value']=='110'
    tick(app,'facts',facts(130,unit='EUR'),NOW+4*INTERVAL)
    assert a.get('/api/v1/notifications?category=periods').json()['items'][0]['kind']=='new_metric_period'
    assert number(Decimal('12345678901234567890.123456789012345678'))=='12345678901234567890.123456789012345678'


def test_source_failure_backoff_recovery_and_account_revocation(workspace):
    app,connect=workspace;a=connect();setup(a,app)
    tick(app,'submissions',submissions(filing()))
    error=HTTPException(502,'Never expose secret@example.test or provider response')
    tick(app,'submissions',error,NOW+INTERVAL)
    tick(app,'submissions',error,NOW+INTERVAL+300)
    assert len(items(a))==1 and 'secret@' not in json.dumps(items(a))
    with Session(app.state.engine) as db:
        source=db.get(MonitorSource,'jpm-submissions')
        assert source.last_success==NOW and source.next_check==NOW+INTERVAL+900
        assert db.scalar(select(func.count()).select_from(MonitorSnapshot))==1
    tick(app,'submissions',submissions(filing()),NOW+2*INTERVAL)
    assert {r['kind'] for r in items(a)}=={'source_error','source_recovered'}
    with Session(app.state.engine) as db,db.begin(): db.scalar(select(User).where(User.login=='alice')).active=False
    with Session(app.state.engine) as db,db.begin(): db.get(MonitorSource,'jpm-submissions').next_check=0
    assert process_monitor(app.state.engine,app.state.settings,lambda *a,**k:pytest.fail('Inactive user triggered fetch'),NOW+3*INTERVAL) is False


def test_manual_queue_cooldown_coverage_and_no_cross_user_access(workspace):
    app,connect=workspace;a=connect();b=connect('bob')
    assert a.post('/api/v1/monitoring/sber/check').status_code==409
    assert a.post('/api/v1/monitoring/jpm/check').status_code==409
    setup(a,app);assert a.post('/api/v1/monitoring/jpm/check').status_code==202
    assert b.post('/api/v1/monitoring/jpm/check').status_code==409
    tick(app,'submissions',submissions(filing()),time.time())
    assert a.post('/api/v1/monitoring/jpm/check').status_code==429
    s=a.get('/api/v1/monitoring').json()['companies']
    assert next(c for c in s if c['company_id']=='sber')['coverage']=='english_connector_gap'
    a.delete('/api/v1/favorites/jpm')
    with Session(app.state.engine) as db,db.begin(): db.get(MonitorSource,'jpm-submissions').next_check=0
    assert process_monitor(app.state.engine,app.state.settings,lambda *a,**k:pytest.fail('Unfollowed source fetched')) is False


@pytest.mark.parametrize('change',[lambda d:d.update(cik=1),lambda d:d['filings']['recent']['primaryDocument'].__setitem__(0,'../../evil'),lambda d:d['filings']['recent']['form'].append('10-Q')])
def test_invalid_source_keeps_baseline_and_no_fabricated_changes(workspace,change):
    app,connect=workspace;a=connect();setup(a,app);tick(app,'submissions',submissions(filing()))
    invalid=submissions(filing());change(invalid);tick(app,'submissions',invalid,NOW+INTERVAL)
    assert [r['kind'] for r in items(a)]==['source_error']
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(MonitorSnapshot))==1


def test_submissions_connector_and_financial_form_filter(monkeypatch):
    monkeypatch.setattr('goldenstock.public_sources.time.sleep',lambda _:None)
    def respond(request):
        assert request.url.path=='/submissions/CIK0000019617.json'
        return httpx.Response(200,json=submissions(filing()))
    _,raw,_=fetch('jpm','qa@example.test',httpx.MockTransport(respond),kind='submissions')
    assert len(index('jpm','submissions',raw,NOW))==1
    other=filing('0000019617-26-000002','8-K');other['items']='5.02'
    financial=filing('0000019617-26-000003','8-K');financial['items']='2.02,9.01'
    assert len(index('jpm','submissions',json.dumps(submissions(other,financial)),NOW))==1
    with pytest.raises(HTTPException): fetch('jpm','qa@example.test',kind='http://localhost')


def test_feed_html_and_source_download_integrity(workspace):
    from goldenstock.ui import mount_ui
    from goldenstock.worker import beat
    app,connect=workspace;mount_ui(app);a=connect();setup(a,app,'facts')
    beat(app.state.engine,'reporting-monitor')
    tick(app,'facts',facts());tick(app,'facts',facts(110),NOW+INTERVAL)
    html=a.get('/updates').text
    from pathlib import Path
    Path('.build-monitor-preview.html').write_text(html,encoding='utf-8')
    assert 'Previously reported number changed' in html and '100' in html and '110' in html and 'Mark as read' in html
    assert 'Coverage gap' in html and 'new calculation' in html
    key=items(a)[0]['detail']['after_snapshot_id']
    with Session(app.state.engine) as db,db.begin(): db.get(MonitorSnapshot,key).payload='tampered'
    assert a.get('/api/v1/monitor-snapshots/'+key+'/download').status_code==409


def test_scheduler_health_is_visible(workspace):
    from goldenstock.worker import beat
    app,connect=workspace;a=connect()
    assert a.get('/api/v1/monitoring').json()['scheduler_ready'] is False
    beat(app.state.engine,'reporting-monitor')
    assert a.get('/api/v1/monitoring').json()['scheduler_ready'] is True
    beat(app.state.engine,'reporting-monitor',time.time()-100)
    assert a.get('/api/v1/monitoring').json()['scheduler_ready'] is False


def test_large_bank_recent_array_filters_nonfinancial_filings():
    # SEC JPM recent contains >26k rows, mostly prospectuses; it is not capped at 1000.
    other=filing(form='424B2')
    payload=submissions(*([other]*26518+[filing()]))
    assert len(index('jpm','submissions',json.dumps(payload),NOW))==1


def test_interrupted_delivery_rolls_back_snapshot_and_observations(workspace,monkeypatch):
    import goldenstock.monitoring as module
    app,connect=workspace;a=connect();setup(a,app,'facts');tick(app,'facts',facts())
    original=module.deliver
    def crash(*args,**kwargs): raise RuntimeError('Synthetic interrupted transaction')
    monkeypatch.setattr(module,'deliver',crash)
    with pytest.raises(RuntimeError): tick(app,'facts',facts(110),NOW+INTERVAL)
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(MonitorSnapshot))==1
        observation=db.scalar(select(MonitorObservation).where(MonitorObservation.source_id=='jpm-facts'))
        assert json.loads(observation.payload)['value']=='100'
        assert db.get(MonitorSource,'jpm-facts').last_success==NOW
    assert items(a)==[]
    monkeypatch.setattr(module,'deliver',original)
    tick(app,'facts',facts(110),NOW+INTERVAL)
    assert len(items(a))==1

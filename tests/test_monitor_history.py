"""SEC comparisons use exact matching contexts and retain non-notifying source refreshes."""
import json
from pathlib import Path
import pytest
from sqlalchemy import select,func,text
from sqlalchemy.orm import Session
from test_workspace import workspace
from test_monitoring import setup,tick,items,facts,NOW,INTERVAL,ACC
from goldenstock.monitor_history import compare,identity
from goldenstock.monitor_index import index,encode
from goldenstock.models import MonitorFactVersion,MonitorObservation,Fact,ValuationRun


def entry(value='100',**changes):
    return dict(namespace='us-gaap',tag='Assets',unit='USD',start='',end='2025-12-31',value=value,
        filed='2026-02-01',accession=ACC,form='10-K',url='https://www.sec.gov',definition='Assets of the reporting entity')|changes


@pytest.mark.parametrize('before,after,delta,percent,significant',[
    ('100','105','5','5.00',True),('100','104.999999','4.999999','5.00',False),
    ('100','95','-5','-5.00',True),('-100','-95','5','5.00',True),
    ('0','120','120',None,False),('0','0','0',None,False),
    ('12345678901234567890.123456789012345678','12345678901234567890.123456789012345679','0.000000000000000001','0.00',False)])
def test_exact_delta_and_threshold(before,after,delta,percent,significant):
    result=compare(entry(before),entry(after))
    assert result['delta']==delta and result['percent']==percent and result['significant'] is significant


@pytest.mark.parametrize('change',[{'unit':'EUR'},{'end':'2026-03-31'},{'start':'2025-01-01'},
    {'namespace':'ifrs-full'},{'tag':'Equity'},{'definition':'Different perimeter or concept'}])
def test_context_mismatch_has_no_automatic_delta(change):
    result=compare(entry(),entry('105',**change))
    assert result['reason']=='different_context' and result['delta'] is None and not result['significant']
    assert compare(None,entry('105'))['reason']=='new_metric_period'


def test_history_republication_reversions_and_no_duplicate_notifications(workspace):
    app,connect=workspace;a=connect();b=connect('bob');setup(a,app,'facts')
    for i,value in enumerate([100,105,105,100,105]):
        tick(app,'facts',facts(value,acc=f'0000019617-26-{i+1:06d}',filed=f'2026-0{i+2}-01'),NOW+i*INTERVAL)
    feed=items(a);assert len(feed)==3
    assert [x['comparison']['significant'] for x in feed]==[True,False,True]
    key=feed[0]['item_key'];url=f'/api/v1/monitoring/jpm-facts/history/{key}'
    history=a.get(url).json()['items']
    assert [r['value']['value'] for r in history]==['105','100','105','105','100']
    assert [r['revision'] for r in history]==[5,4,3,2,1]
    assert history[2]['reason']=='source_refresh'
    assert all(history[i]['previous_id']==history[i+1]['id'] for i in range(4))
    # Numeric publication comparison uses the immediately preceding observation.
    assert feed[1]['detail']['before']['accession']=='0000019617-26-000003'
    tick(app,'facts',facts(105,acc='0000019617-26-000005',filed='2026-06-01'),NOW+5*INTERVAL)
    tick(app,'facts',facts(200),NOW+6*INTERVAL)  # Older filing cannot rewind observations.
    assert len(items(a))==3 and len(a.get(url).json()['items'])==5
    assert items(b)==[] and b.post('/api/v1/notifications/'+feed[0]['id']+'/read').status_code==404
    assert b.get(url).json()==a.get(url).json()  # SEC evidence is public; personal feed/read state is not.
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Fact))==0
        assert db.scalar(select(func.count()).select_from(ValuationRun))==0


def test_periods_missing_rows_definition_change_and_filters(workspace):
    app,connect=workspace;a=connect();setup(a,app,'facts');tick(app,'facts',facts())
    tick(app,'facts',facts(106,'0000019617-26-000002','2026-03-01'),NOW+INTERVAL)
    tick(app,'facts',facts(900,end='2026-03-31'),NOW+2*INTERVAL)
    assert [i['kind'] for i in items(a)]==['possible_revision','new_metric_period']
    period=a.get('/api/v1/notifications?category=periods').json()['items'][0]
    assert period['comparison']['delta'] is None and period['detail']['before'] is None
    tick(app,'facts',dict(cik=19617,facts={}),NOW+3*INTERVAL)
    assert len(a.get('/api/v1/monitoring/jpm-facts/values').json()['items'])==2
    assert len(items(a))==2  # Absence is not zero or deletion.
    assert a.get('/api/v1/notifications?category=bad').status_code==422
    assert a.get('/api/v1/monitoring/jpm-facts/history/bad').status_code==422
    assert a.get('/api/v1/monitoring/jpm-facts/values?offset=-1').status_code==422


def test_source_refresh_history_html_and_checksum(workspace):
    from goldenstock.ui import mount_ui
    from goldenstock.worker import beat
    app,connect=workspace;mount_ui(app);a=connect();setup(a,app,'facts');beat(app.state.engine,'reporting-monitor')
    def payload(value,acc,filed):
        data=facts(value,acc,filed);data['facts']['us-gaap']['Assets'].update(label='Total assets',description='Synthetic assets of the entire filing entity')
        return data
    tick(app,'facts',payload(100,ACC,'2026-02-01'))
    tick(app,'facts',payload(110,'0000019617-26-000002','2026-03-01'),NOW+INTERVAL)
    tick(app,'facts',payload(110,'0000019617-26-000003','2026-04-01'),NOW+2*INTERVAL)
    row=items(a)[0];assert row['comparison']['percent']=='10.00'
    url=f'/monitoring/jpm-facts/history/{row["item_key"]}'
    html=a.get('/updates').text;history_html=a.get(url).text
    assert 'Previous publication' in html and 'New publication' in html and 'Change of at least 5%' in html
    assert 'Source refreshed; numeric value unchanged' in history_html and '0000019617-26-000003' in history_html
    assert 'Synthetic assets of the entire filing entity' in html
    folder=Path('.build-monitor-comparison');folder.mkdir(exist_ok=True)
    (folder/'feed.html').write_text(html,encoding='utf-8')
    (folder/'history.html').write_text(history_html,encoding='utf-8')
    (folder/'values.html').write_text(a.get('/monitoring/jpm-facts').text,encoding='utf-8')
    (folder/'receipt.json').write_text(json.dumps(dict(history_url=url)),encoding='utf-8')
    with Session(app.state.engine) as db,db.begin():
        record=db.scalar(select(MonitorFactVersion));record.payload='{}'
    assert a.get('/api/v1'+url).status_code==409
    a.post('/api/v1/auth/logout')
    assert a.get('/api/v1/monitoring/jpm-facts/values').status_code==401


def test_history_upgrade_preserves_existing_observation(workspace):
    from alembic import command
    from alembic.config import Config
    app,connect=workspace
    command.downgrade(Config('alembic.ini'),'0019')
    payload=entry();key=identity(payload);raw=encode(payload)
    with app.state.engine.begin() as db:
        db.execute(text('INSERT INTO monitor_snapshots (id,source_id,sha256,url,payload,created) VALUES (:id,:source,:sha,:url,:payload,:created)'),
            dict(id='a'*32,source='jpm-facts',sha='b'*64,url='https://data.sec.gov/synthetic',payload='{}',created=NOW))
        db.execute(text('INSERT INTO monitor_observations (source_id,item_key,payload,snapshot_id) VALUES (:source,:key,:payload,:snapshot)'),
            dict(source='jpm-facts',key=key,payload=raw,snapshot='a'*32))
    command.upgrade(Config('alembic.ini'),'head')
    with Session(app.state.engine) as db:
        observation=db.get(MonitorObservation,('jpm-facts',key));row=db.get(MonitorFactVersion,observation.history_id)
        assert row.reason=='legacy_baseline' and row.revision==1 and row.previous_id is None and row.payload==raw


def test_history_rolls_back_with_event_delivery(workspace,monkeypatch):
    import goldenstock.monitoring as module
    app,connect=workspace;a=connect();setup(a,app,'facts');tick(app,'facts',facts())
    old=module.deliver
    def crash(*args,**kwargs): raise RuntimeError('Synthetic crash')
    monkeypatch.setattr(module,'deliver',crash)
    with pytest.raises(RuntimeError): tick(app,'facts',facts(105),NOW+INTERVAL)
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(MonitorFactVersion))==1
    monkeypatch.setattr(module,'deliver',old);tick(app,'facts',facts(105),NOW+INTERVAL)
    assert len(items(a))==1

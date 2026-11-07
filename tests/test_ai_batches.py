import json
import time
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from goldenstock.ai_batches import page_windows
from goldenstock.ai_runs import process_ai
from goldenstock.inference import InferenceError
from goldenstock.models import AIRun,AIProposalBatch,Extraction
from test_workspace import workspace
from test_normalization import seed


def source(text,page):
    return dict(text=text,location={'page':page},method='native')


def test_page_boundaries_and_lossless_original_locators():
    text='FY 2025. Assets 312,300 298,001\n'*300
    items=[source('OUTSIDE 999',1),source(text,2),source('Interleaved outside 999',5),source('Equity 900',3)]
    plan=page_windows(dict(items=items,coverage={'total_pages':5}),'v'*32,'s'*64,2,4)
    assert plan['empty_pages']==[4] and len(plan['windows'])>=3
    pieces=[]
    for window in plan['windows']:
        assert len(json.dumps(window['evidence']))<=6000
        for entry in window['evidence']:
            assert entry['item_index'] in (1,3)
            assert entry['location']['page'] in (2,3)
            assert entry['id']=='v'*32+':'+str(entry['item_index'])
            if entry['item_index']==1: pieces.append(entry['text'])
    assert ''.join(pieces)==text


def test_no_truncated_batch_on_limits():
    for first,last in ((0,1),(3,2),(1,26),(99,99)):
        with pytest.raises(ValueError):page_windows(dict(items=[source('profit 2',1)],coverage={'total_pages':30}),'v','s',first,last)
    with pytest.raises(ValueError,match='more than 10'):
        page_windows(dict(items=[source('x '*35000,1)]),'v','s',1,1)
    with pytest.raises(ValueError,match='token exceeds'):
        page_windows(dict(items=[source('x'*7000,1)]),'v','s',1,1)


def prepared(app,client,*,key='batch-source',text=None):
    receipt=seed(client,app,key)
    with Session(app.state.engine) as db,db.begin():
        db.get(Extraction,receipt['version_id']).payload=json.dumps(dict(
            items=[source('Excluded 999',1),source(text or 'Profit 120\n'+'Narrative. '*700,2),source('Equity 900',3)],
            coverage={'total_pages':4,'status':'complete'}))
    params=dict(job_id=receipt['job_id'],page_start=2,page_end=3,profile='qwen4')
    preview=client.get('/api/v1/ai/batches/preview',params=params)
    assert preview.status_code==200,preview.text
    return receipt,params,preview.json()


def create(client,params,plan):
    response=client.post('/api/v1/ai/batches',json=params|dict(plan_hash=plan['plan_hash']))
    assert response.status_code==201,response.text
    return response.json()['id']


class Good:
    def propose(self,evidence,profile):
        assert all(e['location']['page'] in (2,3) for e in evidence)
        return dict(proposals=[],status='unreviewed')


def test_private_atomic_batch_progress_retry_and_ui(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace;mount_ui(app);client=connect()
    receipt,params,plan=prepared(app,client)
    assert 'Start selected-page batch' in client.get('/ai-batch-preview',params=params).text
    assert client.post('/api/v1/ai/batches',json=params|dict(plan_hash='0'*64)).status_code==409
    key=create(client,params,plan); assert create(client,params,plan)==key
    url='/api/v1/ai/batches/'+key
    data=client.get(url).json(); assert data['total']==len(plan['windows'])
    for other in (connect('bob'),connect('eve')):
        assert other.get('/api/v1/ai/batches/preview',params=params).status_code==404
        assert other.get(url).status_code==404
        assert other.get('/ai-batch/'+key).status_code==404
        assert other.post(url+'/cancel').status_code==404
        assert other.post('/api/v1/ai/batches',json=params|dict(plan_hash=plan['plan_hash'])).status_code==404
    assert client.post(url+'/cancel',headers={'x-csrf-token':'bad'}).status_code==403
    first=data['runs'][0]['run_id']
    assert client.post('/api/v1/ai/runs/'+first+'/cancel').status_code==404
    assert client.get('/api/v1/ai/runs?company_id=sber').json()==[]
    class Fail:
        def propose(self,*args):raise InferenceError('synthetic_failure')
    process_ai(app.state.engine,app.state.settings,Fail())
    while process_ai(app.state.engine,app.state.settings,Good()):pass
    data=client.get(url).json()
    assert data['state']=='finished_with_gaps' and data['completed']==data['total']
    assert client.post(url+'/retry').status_code==200
    assert process_ai(app.state.engine,app.state.settings,Good())
    data=client.get(url).json()
    assert data['state']=='succeeded' and data['runs'][0]['attempts']==2
    assert all(r['attempts']==1 for r in data['runs'][1:])
    assert 'Selected-page AI batch' in client.get('/ai-batch/'+key).text
    assert 'Back to selected-page batch' in client.get('/ai-run/'+first).text
    assert 'Cancel task' not in client.get('/ai-run/'+first).text
    assert client.post(url+'/retry').status_code==409


def test_batch_queue_capacity_has_no_partial_writes(workspace):
    app,connect=workspace;client=connect();_,params,plan=prepared(app,client)
    with Session(app.state.engine) as db,db.begin():
        owner=client.get('/api/v1/auth/me').json()
        for n in range(9):
            db.add(AIRun(org_id=owner['org_id'],owner_id=owner['id'],company_id='sber',kind='proposals',
                profile='qwen4',fingerprint=str(n),input='{}'))
    assert client.post('/api/v1/ai/batches',json=params|dict(plan_hash=plan['plan_hash'])).status_code==429
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(AIRun))==9
        assert db.scalar(select(func.count()).select_from(AIProposalBatch))==0


def test_cancel_lease_and_replay(workspace):
    app,connect=workspace;client=connect();_,params,plan=prepared(app,client)
    key=create(client,params,plan);url='/api/v1/ai/batches/'+key
    class Cancel:
        def propose(self,*args):
            assert client.post(url+'/cancel').status_code==200
            assert client.post(url+'/retry').status_code==409
            return dict(proposals=[{'ignored':'late output'}])
    assert process_ai(app.state.engine,app.state.settings,Cancel())
    assert not process_ai(app.state.engine,app.state.settings,Good())
    data=client.get(url).json()
    assert data['counts']=={'cancelled':data['total']}
    assert client.get('/api/v1/ai/runs/'+data['runs'][0]['run_id']).json()['result']=={}
    assert client.post(url+'/retry').status_code==200
    while process_ai(app.state.engine,app.state.settings,Good()):pass
    assert client.get(url).json()['state']=='succeeded'


def test_changed_frozen_input_never_reaches_provider(workspace):
    app,connect=workspace;client=connect();_,params,plan=prepared(app,client)
    key=create(client,params,plan);url='/api/v1/ai/batches/'+key
    run_id=client.get(url).json()['runs'][0]['run_id']
    with Session(app.state.engine) as db,db.begin():
        run=db.get(AIRun,run_id);payload=json.loads(run.input)
        payload['evidence'][0]['text']='Changed 999';run.input=json.dumps(payload)
    class NoCall:
        def propose(self,*args):raise AssertionError('Provider must not be called')
    assert process_ai(app.state.engine,app.state.settings,NoCall())
    assert client.get('/api/v1/ai/runs/'+run_id).json()['error']=='batch_input_changed'
    assert client.get(url).status_code==409


def test_empty_page_gap_and_blank_batch(workspace):
    app,connect=workspace;client=connect();_,params,plan=prepared(app,client,text='<b>Profit 120</b>')
    gap=client.get('/api/v1/ai/batches/preview',params=params|dict(page_start=4,page_end=4)).json()
    assert gap['empty_pages']==[4] and gap['windows']==[]
    assert client.post('/api/v1/ai/batches',json=params|dict(page_start=4,page_end=4,plan_hash=gap['plan_hash'])).status_code==422

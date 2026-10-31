"""API-level lab boundaries, holdout consumption, blind scoring and queue fencing."""
import json
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_workspace import workspace
from test_normalization import seed,context
from test_reviews import decide
from goldenstock.models import AIRun,LabDataset,LabExperiment,User
from goldenstock.ai_runs import process_ai
from goldenstock.inference import inference_spec,PROFILES,Profile,InferenceError
from goldenstock.lab_scoring import counts,aggregate,numeric


def label(evidence):
    return dict(evidence_id=evidence['id'],metric='profit',number_text='2',quote=evidence['text'],
        currency='USD',scale='millions',period=None,perimeter=None,definition=None)


def dataset_payload(client,app,split='development',kind='proposals'):
    receipt=seed(client,app)
    case=dict(job_id=receipt['job_id'],expected=[])
    if kind=='summary':
        fid=client.post('/api/v1/facts',json=context(job_id=receipt['job_id'])).json()['id'];decide(client,fid)
        case=dict(company_id='sber',expected=[])
    payload=dict(title='Synthetic lab reference',kind=kind,split=split,cases=[case],reference_confirmed=True)
    preview=client.post('/api/v1/lab/preview',json=payload)
    assert preview.status_code==200,preview.text
    evidence=preview.json()['cases'][0]['evidence']
    case['expected']=[label(evidence[0])] if kind=='proposals' else [evidence[0]['id']]
    return payload


def create(client,payload):
    result=client.post('/api/v1/lab/datasets',json=payload)
    assert result.status_code==201,result.text
    return result.json()


def launch(client,dataset):
    response=client.post('/api/v1/lab/experiments',json={'dataset_id':dataset['id']})
    assert response.status_code==201,response.text
    return response.json()['id']


class Provider:
    def result(self,evidence,profile,kind):
        spec=inference_spec(kind,profile)
        receipt={k:spec[k] for k in ('model','model_digest','prompt_version','prompt_sha256')}
        assert all('expected' not in e for e in evidence)
        return dict(receipt,seconds=1.25,tokens=30)

    def propose(self,evidence,profile):
        answer=label(evidence[0])
        if profile=='qwen_small': answer['currency']='EUR'
        return dict(self.result(evidence,profile,'proposals'),proposals=[answer])

    def summarize(self,evidence,profile):
        items=[dict(evidence_id=evidence[0]['id'],text=evidence[0]['text'],quote=evidence[0]['text'])]
        return dict(self.result(evidence,profile,'summary'),claims=items,gaps=[])


def finish(app,provider=None):
    for _ in range(8):
        if not process_ai(app.state.engine,app.state.settings,provider or Provider()): return
    raise AssertionError('Queue did not drain')


def review_all(client,key):
    data=client.get('/api/v1/lab/experiments/'+key).json()
    for run in data['runs']:
        if run['state']=='succeeded':
            response=client.post(f'/api/v1/lab/experiments/{key}/runs/{run["id"]}/annotations',json=dict(revision=0,verdict='correct',reason='Checked against the synthetic source'))
            assert response.status_code==201,response.text


@pytest.mark.parametrize('kind',['proposals','summary'])
def test_complete_blind_comparison_and_version_receipt(workspace,kind):
    app,connect=workspace;client=connect();data=create(client,dataset_payload(client,app,kind=kind));key=launch(client,data)
    assert launch(client,data)==key
    assert client.post(f'/api/v1/lab/experiments/{key}/reveal').status_code==409
    finish(app)
    hidden=client.get('/api/v1/lab/experiments/'+key)
    assert all(x not in hidden.text for x in ('qwen','model_digest','seconds','tokens'))
    assert hidden.json()['comparison']==[]
    assert hidden.json()['manifest_hash'] is None
    for run in hidden.json()['runs']:
        assert client.get('/api/v1/ai/runs/'+run['id']).status_code==404
        assert client.post('/api/v1/ai/runs/'+run['id']+'/cancel').status_code==404
    assert client.get('/api/v1/ai/runs?company_id=sber').json()==[]
    assert client.post(f'/api/v1/lab/experiments/{key}/reveal').status_code==409
    review_all(client,key)
    assert client.post(f'/api/v1/lab/experiments/{key}/reveal').status_code==200
    result=client.get('/api/v1/lab/experiments/'+key).json()
    assert result['quality_target_confirmed'] is False
    assert len(result['comparison'])==2
    for row in result['comparison']:
        assert row['metrics']['precision']==row['metrics']['recall']==1
        assert row['seconds']==1.25 and row['tokens']==30 and row['monetary_cost'] is None
        if kind=='proposals': assert row['metrics']['context_accuracy']['currency']==int(row['profile']=='qwen4')
    assert client.post(f'/api/v1/lab/experiments/{key}/retry').status_code==409
    assert client.post(f'/api/v1/lab/experiments/{key}/runs/{result["runs"][0]["id"]}/annotations',json=dict(revision=1,verdict='incorrect',reason='Cannot change after reveal')).status_code==409


def test_private_acl_reference_validation_and_split_contamination(workspace):
    app,connect=workspace;a=connect();payload=dataset_payload(a,app);d=create(a,payload);key=launch(a,d)
    assert create(a,payload)['id']==d['id']
    for other in (connect('bob'),connect('eve')):
        for path in ('datasets/'+d['id'],'experiments/'+key): assert other.get('/api/v1/lab/'+path).status_code==404
        assert other.get('/api/v1/lab/datasets').json()==[]
        assert other.get('/api/v1/lab/experiments').json()==[]
        assert other.post('/api/v1/lab/datasets',json=payload).status_code==404
        assert other.post('/api/v1/lab/experiments',json={'dataset_id':d['id']}).status_code==404
    payload['split']='holdout'
    assert a.post('/api/v1/lab/datasets',json=payload).status_code==409
    payload['split']='development';payload['parent_id']=d['id'];payload['cases'][0]['expected'][0]['currency']='EUR'
    revision=create(a,payload)
    assert revision['revision']==2 and revision['fingerprint']!=d['fingerprint']
    assert a.get('/api/v1/lab/datasets/'+d['id']).json()['snapshot']['cases'][0]['expected'][0]['currency']=='USD'
    payload['cases'][0]['expected'][0]['quote']='invented'
    assert a.post('/api/v1/lab/datasets',json=payload).status_code==422
    payload['reference_confirmed']=False
    assert a.post('/api/v1/lab/datasets',json=payload).status_code==422


def test_holdout_consumption_freezes_labels_and_configuration(workspace,monkeypatch):
    app,connect=workspace;a=connect();payload=dataset_payload(a,app,split='holdout');d=create(a,payload);key=launch(a,d)
    assert create(a,payload)['id']==d['id']
    payload['cases'][0]['expected']=[]
    assert a.post('/api/v1/lab/datasets',json=payload).status_code==409
    p=PROFILES['qwen4'];monkeypatch.setitem(PROFILES,'qwen4',Profile(p.model,'changed'))
    assert a.post('/api/v1/lab/experiments',json={'dataset_id':d['id']}).status_code==409
    finish(app)
    states=a.get('/api/v1/lab/experiments/'+key).json()['runs']
    assert any(r['error']=='experiment_version_changed' for r in states)
    review_all(a,key);assert a.post(f'/api/v1/lab/experiments/{key}/reveal').status_code==200
    comparison=a.get('/api/v1/lab/experiments/'+key).json()['comparison']
    failed=next(r for r in comparison if r['failed'])
    assert failed['metrics']['recall']==0 and failed['metrics']['precision'] is None


def test_annotation_history_stale_writes_and_cancel_fence(workspace):
    app,connect=workspace;a=connect();key=launch(a,create(a,dataset_payload(a,app)))
    class Cancel(Provider):
        def propose(self,evidence,profile):
            assert a.post(f'/api/v1/lab/experiments/{key}/cancel').status_code==200
            assert a.post(f'/api/v1/lab/experiments/{key}/retry').status_code==409
            return super().propose(evidence,profile)
    process_ai(app.state.engine,app.state.settings,Cancel())
    assert all(r['state']=='cancelled' and r['output']=={} for r in a.get('/api/v1/lab/experiments/'+key).json()['runs'])
    assert a.post(f'/api/v1/lab/experiments/{key}/retry').status_code==200
    finish(app)
    run=a.get('/api/v1/lab/experiments/'+key).json()['runs'][0]
    path=f'/api/v1/lab/experiments/{key}/runs/{run["id"]}/annotations'
    annotation=dict(revision=0,verdict='uncertain',reason='Source context needs checking')
    assert a.post(path,json=annotation).status_code==201
    assert a.post(path,json=annotation).status_code==409
    annotation.update(revision=1,verdict='correct',reason='Rechecked source context manually')
    assert a.post(path,json=annotation).status_code==201
    history=a.get('/api/v1/lab/experiments/'+key).json()['runs'][0]['annotations']
    assert [r['verdict'] for r in history]==['uncertain','correct']


def test_corruption_does_not_produce_usable_results(workspace):
    app,connect=workspace;a=connect();d=create(a,dataset_payload(a,app));key=launch(a,d)
    with Session(app.state.engine) as db,db.begin():
        run=db.scalar(select(AIRun).where(AIRun.kind=='lab_proposals'));p=json.loads(run.input);p['evidence'][0]['text']='tampered';run.input=json.dumps(p)
    finish(app)
    assert a.get('/api/v1/lab/experiments/'+key).status_code==409
    with Session(app.state.engine) as db,db.begin():
        db.get(LabDataset,d['id']).payload='{}'
    assert a.get('/api/v1/lab/datasets/'+d['id']).status_code==409


def test_lab_checks_access_again_after_provider_returns(workspace):
    app,connect=workspace;a=connect();launch(a,create(a,dataset_payload(a,app)))
    class Revoke(Provider):
        def propose(self,evidence,profile):
            with Session(app.state.engine) as db,db.begin():
                db.scalar(select(User).where(User.login=='alice')).active=False
            return super().propose(evidence,profile)
    finish(app,Revoke())
    with Session(app.state.engine) as db:
        rows=list(db.scalars(select(AIRun).where(AIRun.kind=='lab_proposals')))
        assert all(r.state=='failed' and r.error=='access_revoked' and r.output=='{}' for r in rows)


def test_lab_discards_receipts_from_wrong_model(workspace):
    app,connect=workspace;a=connect();key=launch(a,create(a,dataset_payload(a,app)))
    class Wrong(Provider):
        def propose(self,evidence,profile):
            return dict(super().propose(evidence,profile),model_digest='different')
    finish(app,Wrong())
    rows=a.get('/api/v1/lab/experiments/'+key).json()['runs']
    assert all(r['state']=='failed' and r['error']=='experiment_receipt_mismatch' and r['output']=={} for r in rows)


def test_micro_scores_penalize_duplicates_wrong_context_and_failed_cases():
    source=dict(id='e',text='Profit 2 USD million.',source_sha256='a'*64)
    gold=label(source);wrong=dict(gold,period='invented')
    values=counts('proposals',[gold],{'proposals':[wrong,wrong]},[source])
    result=aggregate([values,counts('proposals',[gold],{},[source])])
    assert result['precision']==.5 and result['recall']==.5 and result['f1']==.5
    assert result['context_accuracy']['period']==0
    empty=aggregate([counts('summary',[],{'claims':[]},[source])])
    assert empty['precision'] is None and empty['recall'] is None
    assert numeric('(12.5%)')==numeric('-12.50%')


def test_lab_ui_escapes_labels_and_hides_identity(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace;mount_ui(app);a=connect();payload=dataset_payload(a,app)
    payload['title']='<script>bad()</script>';d=create(a,payload);key=launch(a,d);finish(app)
    assert '&lt;script&gt;' in a.get('/lab').text
    assert 'Reference metric 1' in a.get('/lab/new?job_id='+payload['cases'][0]['job_id']).text
    assert 'Compare local models' in a.get('/lab/datasets/'+d['id']).text
    html=a.get('/lab/experiments/'+key).text
    assert 'Save blind judgement' in html and 'qwen' not in html and '<script>bad()' not in html

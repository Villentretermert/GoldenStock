from test_workspace import workspace
from test_normalization import seed
from goldenstock.ai_runs import process_ai
from goldenstock.inference import InferenceError


class FakeProvider:
    def propose(self,evidence,profile):
        return dict(proposals=[],status='unreviewed',profile=profile)


def test_private_deduplicated_queue_and_retry(workspace):
    app,connect=workspace;a=connect();receipt=seed(a,app)
    data=dict(job_id=receipt['job_id'])
    first=a.post('/api/v1/ai/proposals',json=data)
    assert first.status_code==201,first.text
    key=first.json()['id']
    assert a.post('/api/v1/ai/proposals',json=data).json()['id']==key
    for other in (connect('bob'),connect('eve')):
        assert other.get('/api/v1/ai/runs/'+key).status_code==404
        assert other.post('/api/v1/ai/proposals',json=data).status_code==404
        assert other.get('/api/v1/ai/runs?company_id=sber').json()==[]
    assert a.post('/api/v1/ai/runs/'+key+'/cancel').status_code==200
    assert not process_ai(app.state.engine,app.state.settings,FakeProvider())
    assert a.post('/api/v1/ai/runs/'+key+'/retry').status_code==200
    assert process_ai(app.state.engine,app.state.settings,FakeProvider())
    assert a.get('/api/v1/ai/runs/'+key).json()['state']=='succeeded'
    assert a.post('/api/v1/ai/runs/'+key+'/retry').status_code==409


def test_failure_and_cancel_fence(workspace):
    app,connect=workspace;a=connect();receipt=seed(a,app)
    key=a.post('/api/v1/ai/proposals',json=dict(job_id=receipt['job_id'])).json()['id']
    class Cancel:
        def propose(self,*args):
            assert a.post('/api/v1/ai/runs/'+key+'/cancel').status_code==200
            return {'proposals':[{'bad':'late result'}]}
    assert process_ai(app.state.engine,app.state.settings,Cancel())
    result=a.get('/api/v1/ai/runs/'+key).json()
    assert result['state']=='cancelled' and result['result']=={}
    assert a.post('/api/v1/ai/runs/'+key+'/retry').status_code==200
    class Fail:
        def propose(self,*args): raise InferenceError('provider_unavailable')
    process_ai(app.state.engine,app.state.settings,Fail())
    assert a.get('/api/v1/ai/runs/'+key).json()['error']=='provider_unavailable'

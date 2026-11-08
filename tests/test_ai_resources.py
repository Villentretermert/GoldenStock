"""Admission fails closed, CPU requires a private decision, receipts survive retries."""
import json
import time
import subprocess
import pytest
from sqlalchemy.orm import Session
from goldenstock.ai_resources import DeviceGuard,DeviceUnavailable,gpu_memory,LEASE_SECONDS
from goldenstock.ai_runs import process_ai
from goldenstock.inference import OllamaProvider,PROFILES,InferenceError,inference_spec
from goldenstock.models import AIRun,AIExecution
from test_workspace import workspace
from test_normalization import seed


class Runtime(OllamaProvider):
    def __init__(self):
        self.loaded=None;self.calls=[];self.execution_options={};self.wrong=False;self.cleanup=True

    def request(self,path,body=None,timeout=180):
        self.calls.append((path,body))
        if path=='/api/tags': return dict(models=[dict(name=p.model,digest=p.digest) for p in PROFILES.values()])
        if path=='/api/ps': return dict(models=[self.loaded] if self.loaded else [])
        if path=='/api/generate':
            if body['keep_alive']==0:
                if self.cleanup: self.loaded=None
            else:
                selected=next(p for p in PROFILES.values() if p.model==body['model'])
                cpu=body['options']['num_gpu']==0
                self.loaded=dict(name=selected.model,digest=selected.digest,size_vram=0 if cpu!=self.wrong else 4000000000)
            return {}
        raise AssertionError(path)

    def propose(self,evidence,profile):
        spec=inference_spec('proposals',profile)
        return dict(proposals=[],**{k:spec[k] for k in ('model','model_digest','prompt_version','prompt_sha256')})


def memory(free=10000): return dict(total_mib=12288,free_mib=free)
def guard(free=10000): return lambda a,p,d:DeviceGuard(a,p,d,telemetry=lambda:memory(free))
def unavailable(): raise DeviceUnavailable('gpu_telemetry_unavailable')


@pytest.mark.parametrize('output',['','0, 12288, N/A','0, 12288, 13000','0, 12288, 9000\n1, 12288, 9000'])
def test_invalid_telemetry_is_not_zero_or_infinite(monkeypatch,output):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,0,output,''))
    with pytest.raises(DeviceUnavailable): gpu_memory()


def test_missing_utility_and_valid_telemetry(monkeypatch):
    def missing(*a,**k): raise FileNotFoundError()
    monkeypatch.setattr(subprocess,'run',missing)
    with pytest.raises(DeviceUnavailable): gpu_memory()
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,0,'0, 12288, 10000\n',''))
    assert gpu_memory()==memory()


@pytest.mark.parametrize('free',[0,3072,9215])
def test_low_memory_never_loads_a_model(free):
    adapter=Runtime();g=guard(free)(adapter,'qwen4','gpu')
    with pytest.raises(DeviceUnavailable,match='gpu_reserve_unavailable'):
        with g.execution(): pytest.fail('Should not generate')
    assert not adapter.calls and not g.receipt['inference_started']


def test_loaded_reserve_and_cpu_placement_are_verified():
    samples=iter([memory(),memory(3000)])
    adapter=Runtime();g=DeviceGuard(adapter,'qwen4','gpu',lambda:next(samples))
    with pytest.raises(DeviceUnavailable):
        with g.execution(): pytest.fail('Loaded reserve too small')
    assert adapter.loaded is None and g.receipt['cleanup_confirmed']
    adapter=Runtime();adapter.wrong=True
    with pytest.raises(DeviceUnavailable,match='placement_mismatch'):
        with DeviceGuard(adapter,'qwen4','cpu',unavailable).execution(): pytest.fail('CPU used VRAM')
    assert adapter.loaded is None


def test_memory_loss_discards_output_and_cpu_needs_no_gpu_utility():
    adapter=Runtime();samples=iter([memory(),memory(6000),memory(2900)])
    g=DeviceGuard(adapter,'qwen4','gpu',lambda:next(samples))
    with pytest.raises(DeviceUnavailable,match='reserve_lost'):
        with g.execution(): pass
    assert g.receipt['minimum_free_mib']==2900 and adapter.loaded is None
    g=DeviceGuard(adapter,'qwen4','cpu',unavailable)
    with g.execution():
        assert g.receipt['observed_device']=='cpu' and adapter.execution_options['num_gpu']==0
    assert g.receipt['size_vram_bytes']==0 and g.receipt['cleanup_confirmed']


def queued(workspace):
    app,connect=workspace;client=connect();source=seed(client,app)
    key=client.post('/api/v1/ai/proposals',json=dict(job_id=source['job_id'])).json()['id']
    return app,connect,client,key,'/api/v1/ai/runs/'+key


def test_explicit_cpu_private_history_and_cancel(workspace):
    from goldenstock.ui import mount_ui
    app,connect,client,key,url=queued(workspace);mount_ui(app)
    assert client.post(url+'/use-cpu').status_code==409
    adapter=Runtime()
    assert process_ai(app.state.engine,app.state.settings,adapter,guard_factory=guard(4000))
    assert not process_ai(app.state.engine,app.state.settings,adapter,guard_factory=guard())
    before=client.get(url).json()
    assert before['state']=='awaiting_device' and before['result']=={}
    assert 'Run on CPU' in client.get('/ai-run/'+key).text
    for other in (connect('bob'),connect('eve')):
        assert other.post(url+'/use-cpu').status_code==404
        assert other.get(url).status_code==404
    assert client.post(url+'/use-cpu',headers={'x-csrf-token':'bad'}).status_code==403
    assert client.post(url+'/check-gpu').status_code==200
    process_ai(app.state.engine,app.state.settings,adapter,guard_factory=guard(4000))
    assert client.post(url+'/cancel').status_code==200
    assert client.post(url+'/retry').status_code==200
    process_ai(app.state.engine,app.state.settings,adapter,guard_factory=guard(4000))
    assert client.post(url+'/use-cpu').status_code==200
    process_ai(app.state.engine,app.state.settings,adapter,guard_factory=guard(4000))
    data=client.get(url).json()
    assert data['state']=='succeeded' and data['device']=='cpu'
    assert data['executions'][0]==before['executions'][0]
    assert data['executions'][-1]['observed_device']=='cpu'
    assert data['executions'][-1]['inference_started']


def test_cancel_during_load_and_unconfirmed_cleanup_keep_fence(workspace):
    app,connect,client,key,url=queued(workspace)
    class Cancel(Runtime):
        def request(self,path,body=None,timeout=180):
            result=super().request(path,body,timeout)
            if path=='/api/generate' and body['keep_alive']:
                assert client.post(url+'/cancel').status_code==200
                assert client.post(url+'/retry').status_code==409
            return result
        def propose(self,*a): pytest.fail('Cancelled before inference')
    process_ai(app.state.engine,app.state.settings,Cancel(),guard_factory=guard())
    data=client.get(url).json()
    assert data['state']=='cancelled' and not data['executions'][0]['inference_started']
    client.post(url+'/retry');adapter=Runtime();adapter.cleanup=False
    process_ai(app.state.engine,app.state.settings,adapter,guard_factory=guard())
    assert client.get(url).json()['error']=='device_cleanup_unconfirmed'
    assert client.post(url+'/retry').status_code==409
    assert not process_ai(app.state.engine,app.state.settings,Runtime(),guard_factory=guard())


def test_batch_choice_preserves_success_input_and_waiting_quota(workspace):
    from test_ai_batches import prepared,create
    app,connect=workspace;client=connect();_,params,plan=prepared(app,client)
    key=create(client,params,plan);url='/api/v1/ai/batches/'+key
    process_ai(app.state.engine,app.state.settings,Runtime(),guard_factory=guard())
    process_ai(app.state.engine,app.state.settings,Runtime(),guard_factory=guard(100))
    before=client.get(url).json();first=before['runs'][0]['run_id']
    with Session(app.state.engine) as db:
        original={r['run_id']:db.get(AIRun,r['run_id']).input for r in before['runs']}
    assert client.post(url+'/use-cpu').status_code==200
    after=client.get(url).json()
    assert after['runs'][0]['state']=='succeeded' and after['runs'][0]['device']=='gpu'
    assert all(r['device']=='cpu' for r in after['runs'][1:])
    with Session(app.state.engine) as db:
        assert all(db.get(AIRun,k).input==v for k,v in original.items())


def test_lab_resource_wait_stays_blind_and_blocks_reveal(workspace):
    from test_ai_lab import dataset_payload,create,launch,review_all
    app,connect=workspace;client=connect();key=launch(client,create(client,dataset_payload(client,app)))
    url='/api/v1/lab/experiments/'+key
    while process_ai(app.state.engine,app.state.settings,Runtime(),guard_factory=guard(1)): pass
    before=client.get(url).json()
    assert all(r['state']=='awaiting_device' for r in before['runs'])
    assert 'executions' not in json.dumps(before) and 'qwen' not in json.dumps(before)
    assert client.post(url+'/reveal').status_code==409
    assert client.post(url+'/use-cpu').status_code==200
    while process_ai(app.state.engine,app.state.settings,Runtime(),guard_factory=guard(1)): pass
    review_all(client,key)
    assert client.post(url+'/reveal').status_code==200
    data=client.get(url).json()
    assert all(r['executions'][-1]['observed_device']=='cpu' for r in data['runs'])
    assert client.post(url+'/check-gpu').status_code==409


def test_waiting_tasks_use_quota_but_do_not_block_other_analysts(workspace):
    app,connect,client,key,url=queued(workspace)
    process_ai(app.state.engine,app.state.settings,Runtime(),guard_factory=guard(1))
    bob=connect('bob');source=seed(bob,app,'bob-resource-test')
    other=bob.post('/api/v1/ai/proposals',json=dict(job_id=source['job_id'])).json()['id']
    assert process_ai(app.state.engine,app.state.settings,Runtime(),guard_factory=guard())
    assert bob.get('/api/v1/ai/runs/'+other).json()['state']=='succeeded'
    with Session(app.state.engine) as db,db.begin():
        first=db.get(AIRun,key)
        for i in range(9):
            db.add(AIRun(org_id=first.org_id,owner_id=first.owner_id,company_id='sber',
                kind='proposals',profile='qwen4',fingerprint=f'quota-{i}',input=first.input,state='awaiting_device'))
    source=seed(client,app,'another-resource-test')
    assert client.post('/api/v1/ai/proposals',json=dict(job_id=source['job_id'])).status_code==429
    assert client.post(url+'/use-cpu').status_code==200  # A decision does not add an eleventh pending task.


def test_telemetry_loss_after_loading_is_not_success():
    adapter=Runtime();reads=0
    def sample():
        nonlocal reads
        reads+=1
        return memory() if reads<3 else unavailable()
    g=DeviceGuard(adapter,'qwen4','gpu',sample)
    with pytest.raises(DeviceUnavailable,match='telemetry_unavailable'):
        with g.execution(): pass
    assert g.receipt['telemetry_lost'] and g.receipt['cleanup_confirmed']


def test_crash_marks_unfinished_attempt_without_inventing_a_measurement(workspace):
    app,connect,client,key,url=queued(workspace)
    with Session(app.state.engine) as db,db.begin():
        row=db.get(AIRun,key);row.state='cancelled';row.attempts=1;row.lease_until=time.time()-1
        db.add(AIExecution(run_id=key,attempt=1,state='running',started=time.time()-500,
            receipt=json.dumps(dict(requested_device='gpu',policy='gs031-device-v1'))))
    assert not process_ai(app.state.engine,app.state.settings,Runtime(),guard_factory=guard())
    result=client.get(url).json()['executions'][0]
    assert result['state']=='interrupted' and result['finished'] is not None
    assert 'observed_device' not in result and 'seconds' not in result

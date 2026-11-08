"""Local admission control, explicit device selection and bounded resource receipts."""
import json
import subprocess
import threading
import time
from contextlib import contextmanager
from fastapi import HTTPException
from sqlalchemy import select
from goldenstock.inference import InferenceError, PROFILES
from goldenstock.models import AIExecution

POLICY='gs031-device-v1'
RESERVE_MIB=3072
# Conservative admission budgets, not predictions of actual allocation.
GPU_BUDGET_MIB={'qwen4':6144,'qwen_small':4096}
PENDING={'queued','running','awaiting_device'}
LEASE_SECONDS=420  # 90 s preload + 180 s inference + cleanup and telemetry margin.


class DeviceUnavailable(InferenceError):
    """No inference without another explicit analyst decision."""


def gpu_memory():
    """Read only aggregate memory; never enumerate other applications."""
    try:
        result=subprocess.run(['nvidia-smi','--query-gpu=index,memory.total,memory.free',
            '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3,check=True)
        rows=[line for line in result.stdout.splitlines() if line.strip()]
        if len(rows)!=1: raise ValueError('Single GPU pilot only')
        index,total,free=[int(v.strip()) for v in rows[0].split(',')]
        if index!=0 or not 0<=free<=total: raise ValueError('Invalid memory counters')
        return dict(total_mib=total,free_mib=free)
    except (OSError,subprocess.SubprocessError,ValueError):
        raise DeviceUnavailable('gpu_telemetry_unavailable') from None


def history(db,run):
    # Callers authorize the parent run; there is no public attempt endpoint.
    return [dict(attempt=x.attempt,state=x.state,started=x.started,finished=x.finished,
        **json.loads(x.receipt)) for x in db.scalars(select(AIExecution).where(
            AIExecution.run_id==run.id).order_by(AIExecution.attempt))]


def choose_device(runs,action):
    """Only pending work changes; completed answers and frozen inputs are untouched."""
    if not any(r.state=='awaiting_device' for r in runs):
        raise HTTPException(409,'Wait for a resource decision before changing device')
    targets=[r for r in runs if r.state in {'queued','awaiting_device'}]
    if any(r.lease_until>time.time() for r in targets):
        raise HTTPException(409,'Wait for the provider to release its lease')
    for row in targets:
        row.device='cpu' if action=='use-cpu' else 'gpu'
        row.state='queued';row.error='';row.lease_token=''


class DeviceGuard:
    def __init__(self,adapter,profile,device,telemetry=gpu_memory):
        self.adapter=adapter;self.profile=profile;self.device=device;self.telemetry=telemetry
        self.receipt=dict(policy=POLICY,requested_device=device,observed_device=None,
            reserve_mib=RESERVE_MIB,budget_mib=GPU_BUDGET_MIB[profile],inference_started=False,
            telemetry_lost=False,reserve_breached=False,cleanup_confirmed=True)
        self.stop=threading.Event();self.thread=None

    def sample(self):
        try:
            data=self.telemetry();free=data['free_mib']
            self.receipt['total_mib']=data['total_mib']
            self.receipt['minimum_free_mib']=min(free,self.receipt.get('minimum_free_mib',free))
            if free<RESERVE_MIB: self.receipt['reserve_breached']=True
            return free
        except DeviceUnavailable:
            self.receipt['telemetry_lost']=True
            raise

    def monitor(self):
        while not self.stop.wait(1):
            try: self.sample()
            except DeviceUnavailable: pass  # Mark the receipt; never silently claim a reserve.

    @contextmanager
    def execution(self):
        start=time.monotonic();loaded=False
        selected=PROFILES[self.profile]
        options=dict(num_gpu=0 if self.device=='cpu' else 999,num_thread=2)
        self.receipt['options']=options
        try:
            if self.device not in {'gpu','cpu'}: raise InferenceError('invalid_device')
            if self.device=='gpu':
                free=self.sample();self.receipt['free_before_mib']=free
                if free<RESERVE_MIB+GPU_BUDGET_MIB[self.profile]:
                    raise DeviceUnavailable('gpu_reserve_unavailable')
            models=self.adapter.request('/api/ps',timeout=5).get('models',[])
            if models: raise DeviceUnavailable('provider_busy')
            tags=self.adapter.request('/api/tags',timeout=5).get('models',[])
            if not any(m.get('name')==selected.model and m.get('digest')==selected.digest for m in tags):
                raise InferenceError('model_digest_mismatch')
            # Set before loading: a timeout may still have left a resident runner.
            loaded=True;self.receipt['cleanup_confirmed']=False
            self.adapter.execution_options=options
            self.adapter.request('/api/generate',dict(model=selected.model,stream=False,
                keep_alive=300,options=dict(options,num_ctx=selected.context)),timeout=90)
            models=self.adapter.request('/api/ps',timeout=5).get('models',[])
            model=next((m for m in models if m.get('name')==selected.model and m.get('digest')==selected.digest),None)
            size=model.get('size_vram') if model else None
            if not isinstance(size,int) or isinstance(size,bool) or size<0 or len(models)!=1:
                raise DeviceUnavailable('device_placement_unverified')
            self.receipt.update(observed_device='gpu' if size else 'cpu',size_vram_bytes=size)
            if self.receipt['observed_device']!=self.device:
                raise DeviceUnavailable('device_placement_mismatch')
            if self.device=='gpu':
                self.receipt['free_loaded_mib']=self.sample()
                if self.receipt['reserve_breached']: raise DeviceUnavailable('gpu_reserve_unavailable')
                self.thread=threading.Thread(target=self.monitor,daemon=True);self.thread.start()
            yield self.receipt
            if self.device=='gpu':
                self.sample()
                if self.receipt['reserve_breached']: raise DeviceUnavailable('gpu_reserve_lost')
                if self.receipt['telemetry_lost']: raise DeviceUnavailable('gpu_telemetry_unavailable')
        finally:
            self.stop.set()
            if self.thread: self.thread.join(timeout=4)
            try:
                if loaded:
                    self.adapter.request('/api/generate',dict(model=selected.model,stream=False,keep_alive=0),timeout=5)
                    self.receipt['cleanup_confirmed']=not self.adapter.request('/api/ps',timeout=5).get('models',[])
            except InferenceError:
                self.receipt['cleanup_confirmed']=False
            self.receipt['seconds']=round(time.monotonic()-start,3)
            if loaded and not self.receipt['cleanup_confirmed']:
                raise InferenceError('device_cleanup_unconfirmed')

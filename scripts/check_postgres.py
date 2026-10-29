"""Run via stdin inside web; isolate all fixture rows in a disposable PG schema."""
import os
import secrets
import tempfile
import subprocess
import sys
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text,select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from goldenstock.config import get_settings,Settings
from goldenstock.db import make_engine
from goldenstock.models import Organization,User,Job,JobEvent,Extraction,Fact
from goldenstock.auth import hash_password
from goldenstock.api import create_app
from goldenstock.jobs import claim,execute


def main():
    original=get_settings()
    operator=make_engine(original)
    schema='qa_'+secrets.token_hex(10)
    with operator.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA {schema}'))
    app=None
    try:
        url=make_url(original.database_url).update_query_dict({'options':f'-csearch_path={schema}'})
        os.environ['GS_DATABASE_URL']=url.render_as_string(hide_password=False)
        get_settings.cache_clear()
        command.upgrade(Config('alembic.ini'),'head')
        command.upgrade(Config('alembic.ini'),'head')
        with tempfile.TemporaryDirectory(prefix='gs-qa-') as directory:
            settings=Settings(database_url=os.environ['GS_DATABASE_URL'],data_dir=Path(directory),public_url='http://testserver')
            app=create_app(settings)
            password=secrets.token_urlsafe(24)
            with Session(app.state.engine) as db,db.begin():
                org=Organization(name='Synthetic QA');db.add(org);db.flush()
                db.add(User(org_id=org.id,login='qa',password_hash=hash_password(password)))
            with TestClient(app) as client:
                client.headers['origin']='http://testserver'
                response=client.post('/api/v1/auth/login',json={'login':'qa','password':password})
                assert response.status_code==200
                client.headers['x-csrf-token']=response.json()['csrf']
                def upload():
                    return client.post('/api/v1/documents',headers={'Idempotency-Key':'postgres-concurrent'},
                        data={'company_id':'sber'},files={'file':('report.pdf',b'%PDF-1.4\nsynthetic PG fixture')})
                with ThreadPoolExecutor(max_workers=4) as pool:
                    uploads=list(pool.map(lambda _:upload(),range(4)))
                assert all(r.status_code==201 for r in uploads), 'Concurrent idempotency failed'
                assert len({r.json()['version_id'] for r in uploads})==1
                with ThreadPoolExecutor(max_workers=4) as pool:
                    leases=list(pool.map(lambda _:claim(app.state.engine,100),range(4)))
                claimed=[lease for lease in leases if lease]
                assert len(claimed)==1,'Multiple claims'
                # A separate process commits a claim and crashes before completion.
                crashed=subprocess.run([sys.executable,'-c',
                    'import os; from goldenstock.jobs import claim; from goldenstock.db import make_engine; from goldenstock.config import get_settings; assert claim(make_engine(get_settings()),161); os._exit(17)'])
                assert crashed.returncode==17
                replacement=claim(app.state.engine,222)
                assert replacement and replacement!=claimed[0]
                execute(app.state.engine,settings,claimed[0],223)
                with Session(app.state.engine) as db:
                    assert db.get(Job,replacement[0]).state=='running'
                execute(app.state.engine,settings,replacement,224)
                with Session(app.state.engine) as db:
                    assert db.get(Job,replacement[0]).state=='succeeded'
                    assert len(list(db.scalars(select(Job))))==1
                    assert len(list(db.scalars(select(JobEvent))))==5
                receipt=uploads[0].json()
                with Session(app.state.engine) as db,db.begin():
                    db.add(Extraction(version_id=receipt['version_id'],source_sha256=receipt['sha256'],
                        parser_version='synthetic',payload=json.dumps({'items':[dict(text='120',location={'page':1},method='native')]})))
                fact=dict(job_id=receipt['job_id'],item_index=0,number_text='120',metric='profit',unit='money',
                    scale='millions',currency='USD',period_kind='year',period_start='2025-01-01',period_end='2025-12-31',
                    scope='group',scope_detail='Synthetic group',accounting='IFRS',definition='Total profit after tax')
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results=list(pool.map(lambda _:client.post('/api/v1/facts',json=fact),range(4)))
                assert all(r.status_code==201 for r in results)
                assert len({r.json()['id'] for r in results})==1
                previous=results[0].json()['id']
                with ThreadPoolExecutor(max_workers=2) as pool:
                    corrections=list(pool.map(lambda scale:client.post('/api/v1/facts',json=fact|{
                        'scale':scale,'supersedes':previous}),['thousands','units']))
                assert sorted(r.status_code for r in corrections)==[201,409]
                with Session(app.state.engine) as db:
                    assert len(list(db.scalars(select(Fact))))==2
                current=next(r.json()['id'] for r in corrections if r.status_code==201)
                decision=dict(expected_revision=0,decision='accepted',note='Checked synthetic original')
                with ThreadPoolExecutor(max_workers=2) as pool:
                    reviews=list(pool.map(lambda _:client.post('/api/v1/facts/'+current+'/reviews',json=decision),range(2)))
                assert sorted(r.status_code for r in reviews)==[201,409]
                digest=client.get('/api/v1/review-state?company_id=sber').json()['state_hash']
                payload=dict(company_id='sber',title='Concurrent snapshot',expected_state_hash=digest)
                with ThreadPoolExecutor(max_workers=3) as pool:
                    saved=list(pool.map(lambda _:client.post('/api/v1/input-snapshots',json=payload),range(3)))
                assert all(r.status_code==201 for r in saved)
                assert len({r.json()['id'] for r in saved})==1
                from goldenstock.ai_runs import process_ai
                import threading
                import time
                with ThreadPoolExecutor(max_workers=3) as pool:
                    queued=list(pool.map(lambda _:client.post('/api/v1/ai/proposals',json={'job_id':receipt['job_id']}),range(3)))
                assert all(r.status_code==201 for r in queued)
                assert len({r.json()['id'] for r in queued})==1
                calls=[];entered=threading.Event();release=threading.Event()
                class Provider:
                    def propose(self,*args):
                        calls.append(1);entered.set();assert release.wait(10)
                        return {'proposals':[],'status':'unreviewed'}
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first=pool.submit(process_ai,app.state.engine,settings,Provider())
                    assert entered.wait(10)
                    assert process_ai(app.state.engine,settings,Provider()) is False
                    release.set();assert first.result()
                assert len(calls)==1
                demo=client.get('/api/v1/templates/demo').content
                def template_upload(key,template_id=''):
                    return client.post('/api/v1/templates',headers={'Idempotency-Key':key},
                        data={'title':'Synthetic concurrency template','template_id':template_id},
                        files={'file':('template.xlsx',demo)})
                with ThreadPoolExecutor(max_workers=3) as pool:
                    templates=list(pool.map(lambda _:template_upload('pg-template-first'),range(3)))
                assert all(t.status_code==201 for t in templates)
                assert len({t.json()['id'] for t in templates})==1
                template_id=templates[0].json()['template_id']
                with ThreadPoolExecutor(max_workers=2) as pool:
                    versions=list(pool.map(lambda k:template_upload(k,template_id),['pg-template-v2','pg-template-v3']))
                assert sorted(t.json()['number'] for t in versions)==[2,3]
                # A copy holds the visibility/version lock until it picks its source.
                import goldenstock.templates as template_api
                original_access=template_api.access
                copy_locked=threading.Event();finish_copy=threading.Event()
                def gated_access(*args,**kwargs):
                    result=original_access(*args,**kwargs)
                    if not (kwargs.get('write') or (len(args)>3 and args[3])):
                        copy_locked.set();assert finish_copy.wait(10)
                    return result
                template_api.access=gated_access
                try:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        copying=pool.submit(client.post,'/api/v1/templates/'+template_id+'/copy')
                        assert copy_locked.wait(10)
                        newer=pool.submit(template_upload,'pg-template-v4',template_id)
                        time.sleep(.2)
                        assert not newer.done(),'New version overtook a locked source selection'
                        finish_copy.set()
                        assert copying.result().status_code==201
                        assert newer.result().json()['number']==4
                finally: template_api.access=original_access
                # Concurrent calculation retries have one immutable receipt.
                version=templates[0].json()
                calculation=dict(title='Synthetic PostgreSQL calculation',company_id='sber',
                    template_id=template_id,version_id=version['id'],snapshot_id=saved[0].json()['id'],
                    scenarios={'base':{
                        'profit_owners':dict(fact_id=current,note='Synthetic source definition and perimeter checked',confirmed=True),
                        'growth':dict(value='0.05',note='Synthetic growth assumption',confirmed=True)}},checks=[])
                def calculate_once(key):
                    return client.post('/api/v1/calculations',json=calculation,headers={'Idempotency-Key':key})
                with ThreadPoolExecutor(max_workers=3) as pool:
                    runs=list(pool.map(lambda _:calculate_once('pg-calculation-first'),range(3)))
                assert all(r.status_code==201 for r in runs),[r.text for r in runs]
                assert len({r.json()['id'] for r in runs})==1
                run_id=runs[0].json()['id']
                assert client.post('/api/v1/calculations/'+run_id+'/replay').json()['matched']
                # A review cannot change a fact while the calculation takes its snapshot.
                import goldenstock.calculations as calculation_api
                original_state=calculation_api.review_state
                calculation_locked=threading.Event();finish_calculation=threading.Event()
                def gated_state(*args,**kwargs):
                    result=original_state(*args,**kwargs)
                    calculation_locked.set();assert finish_calculation.wait(10)
                    return result
                calculation_api.review_state=gated_state
                try:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        creating=pool.submit(calculate_once,'pg-calculation-review-race')
                        assert calculation_locked.wait(10)
                        revising=pool.submit(client.post,'/api/v1/facts/'+current+'/reviews',json={
                            'expected_revision':1,'decision':'unreviewed','note':'Synthetic concurrent review change'})
                        time.sleep(.2)
                        assert not revising.done(),'Review overtook a locked calculation snapshot'
                        finish_calculation.set()
                        assert creating.result().status_code==201
                        assert revising.result().status_code==201
                finally: calculation_api.review_state=original_state
                assert calculate_once('pg-calculation-stale').status_code==409
                assert client.get('/api/v1/calculations/'+run_id).json()['inputs_current'] is False
                # Sharing changes use the same lock order as calculations and uploads.
                calculation.pop('snapshot_id')
                calculation['scenarios']['base']['profit_owners']=dict(value='100',note='Synthetic manual input',confirmed=True)
                revision=client.get('/api/v1/templates/'+template_id).json()['revision']
                with ThreadPoolExecutor(max_workers=2) as pool:
                    calculating=pool.submit(calculate_once,'pg-calculation-visibility-race')
                    sharing=pool.submit(client.patch,'/api/v1/templates/'+template_id+'/visibility',json={'shared':True,'revision':revision})
                    assert calculating.result().status_code==201
                    assert sharing.result().status_code==200
                # Valuations serialize receipts and fence source-review changes too.
                assert client.post('/api/v1/facts/'+current+'/reviews',json={
                    'expected_revision':2,'decision':'accepted','note':'Synthetic renewed review for valuation'}).status_code==201
                digest=client.get('/api/v1/review-state?company_id=sber').json()['state_hash']
                fresh=client.post('/api/v1/input-snapshots',json=dict(company_id='sber',title='Valuation source',expected_state_hash=digest)).json()['id']
                calculation['snapshot_id']=fresh
                calculation['scenarios']['base']['profit_owners']=dict(fact_id=current,note='Synthetic common profit checked',confirmed=True)
                fresh_calculation=calculate_once('pg-valuation-source').json()['id']
                valuation=dict(calculation_id=fresh_calculation,title='Synthetic PostgreSQL valuation',method='pe',currency='USD',
                    valuation_date='2025-12-31',reference_year=2025,method_note='Synthetic comparable banks and multiple basis',
                    scope_note='Synthetic common equity, excluding non-controlling interests',
                    shares_note='Synthetic ordinary common shares, no ADR conversion',method_confirmed=True,comparability_confirmed=True,
                    scenarios={'base':{key:dict(value=value,note='Synthetic confirmed assumption',confirmed=True)
                        for key,value in dict(shares='10',profit_owners='100',preferred_dividends='0',multiple='10').items()}})
                def value_once(key):
                    return client.post('/api/v1/valuations',json=valuation,headers={'Idempotency-Key':key})
                with ThreadPoolExecutor(max_workers=3) as pool:
                    valuations=list(pool.map(lambda _:value_once('pg-valuation-first'),range(3)))
                assert all(r.status_code==201 for r in valuations),[r.text for r in valuations]
                assert len({r.json()['id'] for r in valuations})==1
                valuation_id=valuations[0].json()['id']
                import goldenstock.valuations as valuation_api
                original_current=valuation_api.source_current
                valuation_locked=threading.Event();finish_valuation=threading.Event()
                def gated_current(*args,**kwargs):
                    result=original_current(*args,**kwargs)
                    valuation_locked.set();assert finish_valuation.wait(10)
                    return result
                valuation_api.source_current=gated_current
                try:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        valuing=pool.submit(value_once,'pg-valuation-review-race')
                        assert valuation_locked.wait(10)
                        revising=pool.submit(client.post,'/api/v1/facts/'+current+'/reviews',json={
                            'expected_revision':3,'decision':'unreviewed','note':'Synthetic concurrent valuation review change'})
                        time.sleep(.2)
                        assert not revising.done(),'Review overtook a locked valuation snapshot'
                        finish_valuation.set()
                        assert valuing.result().status_code==201
                        assert revising.result().status_code==201
                finally: valuation_api.source_current=original_current
                assert value_once('pg-valuation-stale').status_code==409
                assert client.get('/api/v1/valuations/'+valuation_id).json()['inputs_current'] is False
                assert client.post('/api/v1/valuations/'+valuation_id+'/replay').json()['matched']
                print('Valuation PostgreSQL PASS: idempotent receipts, review fencing, stale source rejection and historical replay.')
                print('Calculation PostgreSQL PASS: idempotency, replay, review fencing and stale input rejection.')
                print('Template PostgreSQL PASS: idempotent upload and unique concurrent version numbers.')
                print('PostgreSQL integration PASS: migrations, concurrent upload/fact/review/snapshot/AI deduplication, single GPU task, single successor, crash recovery and stale-worker fencing.')
    finally:
        if app:
            app.state.engine.dispose()
        with operator.begin() as connection:
            # Only this random schema created by this invocation can be removed.
            assert schema.startswith('qa_') and len(schema)==23
            connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        operator.dispose()


if __name__=='__main__':
    main()

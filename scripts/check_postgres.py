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

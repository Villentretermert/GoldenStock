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


def check_pdf_resume(app, client):
    import io
    import threading
    from unittest.mock import patch
    from reportlab.pdfgen import canvas
    from goldenstock import jobs
    from goldenstock.models import ExtractionCheckpoint
    stream=io.BytesIO(); pdf=canvas.Canvas(stream)
    for number in range(1,27):
        pdf.drawString(50,750,f'Original synthetic page {number}'); pdf.showPage()
    pdf.save()
    response=client.post('/api/v1/documents',data={'company_id':'jpm'},
        headers={'Idempotency-Key':'pg-pdf-checkpoint'},files={'file':('annual.pdf',stream.getvalue())})
    response.raise_for_status(); receipt=response.json()
    jobs.process_one(app.state.engine,app.state.settings)
    url='/api/v1/jobs/'+receipt['job_id']
    client.post(url+'/extract').raise_for_status()
    leased=claim(app.state.engine)
    saved=threading.Event(); release=threading.Event()
    save=jobs.save_pdf_checkpoint
    def paused(*args):
        save(*args); saved.set(); assert release.wait(15)
    with patch.object(jobs,'save_pdf_checkpoint',paused), ThreadPoolExecutor(max_workers=1) as pool:
        executing=pool.submit(execute,app.state.engine,app.state.settings,leased)
        try:
            assert saved.wait(30)
            assert client.get(url).json()['progress']['completed_pages']==25
            client.post(url+'/cancel').raise_for_status()
        finally:
            release.set()
        executing.result()
    assert client.get(url).json()['state']=='cancelled'
    assert client.get(url+'/extraction').status_code==409
    with Session(app.state.engine) as db:
        prefix=json.loads(db.get(ExtractionCheckpoint,receipt['version_id']).payload)
    from goldenstock.extraction import ExtractionError
    try:
        save(app.state.engine,*leased,receipt['sha256'],prefix)
        raise AssertionError('Cancelled worker overwrote checkpoint')
    except ExtractionError as exc:
        assert str(exc)=='lease_or_access_lost'
    client.post(url+'/retry').raise_for_status()
    jobs.process_one(app.state.engine,app.state.settings)
    result=client.get(url+'/extraction'); result.raise_for_status()
    assert result.json()['source_sha256']==receipt['sha256']
    assert [i['location']['page'] for i in result.json()['items']]==list(range(1,27))
    print('PDF PostgreSQL PASS: checkpoint survives concurrent cancellation, stale write fenced, resume preserves 26 original pages.')


def check_template_publications(app,client,password):
    from goldenstock.models import TemplatePublication,TemplateNotification
    author=client.get('/api/v1/auth/me').json()
    with Session(app.state.engine) as db,db.begin():
        user=db.get(User,author['id'])
        db.add(User(org_id=user.org_id,login='publication-peer',password_hash=user.password_hash))
    with TestClient(app) as peer:
        peer.headers['origin']='http://testserver'
        auth=peer.post('/api/v1/auth/login',json=dict(login='publication-peer',password=password));auth.raise_for_status()
        peer.headers['x-csrf-token']=auth.json()['csrf']
        demo=client.get('/api/v1/templates/demo').content
        def upload(session,key):
            r=session.post('/api/v1/templates',headers={'Idempotency-Key':key},data={'title':'Synthetic publication concurrency'},files={'file':('template.xlsx',demo)})
            r.raise_for_status();return r.json()['template_id']
        first,second=upload(client,'pg-publish-author'),upload(peer,'pg-publish-peer')
        def publish(session,tid,revision=1):
            return session.patch('/api/v1/templates/'+tid+'/visibility',json=dict(shared=True,revision=revision))
        # Two authors hold their own user locks; fanout must not request cross-user FK locks.
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(publish,client,first);b=pool.submit(publish,peer,second)
            assert a.result(timeout=20).status_code==b.result(timeout=20).status_code==200
        with ThreadPoolExecutor(max_workers=4) as pool:
            repeated=list(pool.map(lambda _:publish(client,first,2),range(4)))
        assert sorted(r.status_code for r in repeated)==[200,409,409,409]
        with Session(app.state.engine) as db:
            pubs=list(db.scalars(select(TemplatePublication).where(TemplatePublication.template_id.in_([first,second]))))
            assert len(pubs)==2
            receipts=list(db.scalars(select(TemplateNotification).where(TemplateNotification.publication_id.in_([p.id for p in pubs]))))
            assert len(receipts)==4
        items=[i for i in peer.get('/api/v1/template-updates').json()['items'] if i['template_id']==first]
        assert len(items)==1
        read_url='/api/v1/template-updates/'+items[0]['id']+'/read'
        with ThreadPoolExecutor(max_workers=3) as pool:
            read=list(pool.map(lambda _:peer.post(read_url),range(3)))
        assert all(r.status_code==200 for r in read) and len({r.json()['read_at'] for r in read})==1
        client.patch('/api/v1/templates/'+first+'/visibility',json=dict(shared=False,revision=3)).raise_for_status()
        assert peer.post(read_url).status_code==404
    print('Template publication PostgreSQL PASS: parallel authors, one publication and receipt per reader, concurrent read state and withdrawn access.')


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
                # AI Lab uses the same scheduling lock and immutable reference rows.
                from goldenstock.inference import inference_spec
                lab_payload=dict(title='Synthetic PostgreSQL lab',kind='proposals',split='development',
                    reference_confirmed=True,cases=[dict(job_id=receipt['job_id'],expected=[])])
                with ThreadPoolExecutor(max_workers=3) as pool:
                    lab_datasets=list(pool.map(lambda _:client.post('/api/v1/lab/datasets',json=lab_payload),range(3)))
                assert all(r.status_code==201 for r in lab_datasets),[r.text for r in lab_datasets]
                assert len({r.json()['id'] for r in lab_datasets})==1
                lab_dataset=lab_datasets[0].json()['id']
                # Workbook previews and confirmations serialize under the same source lock.
                from openpyxl import load_workbook
                import io
                exchange=client.post('/api/v1/lab/exchange/datasets/'+lab_dataset).json()['id']
                raw=client.get('/api/v1/lab/exchange/drafts/'+exchange+'/download').content
                book=load_workbook(io.BytesIO(raw))
                source=client.get('/api/v1/lab/exchange/drafts/'+exchange).json()['cases'][0]['evidence'][0]
                values=[source['id'],'profit','2',source['text'],'USD','millions','','','Synthetic reference']
                for col,value in enumerate(values,3):
                    cell=book['Labels'].cell(5,col,value);cell.data_type='s'
                book['Cases']['C5']='labelled';buffer=io.BytesIO();book.save(buffer);book.close()
                raw=buffer.getvalue()
                with ThreadPoolExecutor(max_workers=3) as pool:
                    imports=list(pool.map(lambda _:client.post('/api/v1/lab/exchange/imports',files={'file':('labels.xlsx',raw)}),range(3)))
                assert all(r.status_code==201 for r in imports),[r.text for r in imports]
                assert len({r.json()['id'] for r in imports})==1
                import_url='/api/v1/lab/exchange/imports/'+imports[0].json()['id']
                confirmation=dict(candidate_hash=client.get(import_url).json()['candidate_hash'],reference_confirmed=True,reason='Synthetic PostgreSQL review')
                with ThreadPoolExecutor(max_workers=3) as pool:
                    confirmed=list(pool.map(lambda _:client.post(import_url+'/confirm',json=confirmation),range(3)))
                assert all(r.status_code==200 for r in confirmed),[r.text for r in confirmed]
                assert len({r.json()['id'] for r in confirmed})==1 and confirmed[0].json()['revision']==2
                assert client.get(import_url+'/original').content==raw
                print('Workbook PostgreSQL PASS: concurrent import and confirmation deduplication, immutable revision and retained XLSX.')
                with ThreadPoolExecutor(max_workers=3) as pool:
                    lab_experiments=list(pool.map(lambda _:client.post('/api/v1/lab/experiments',json={'dataset_id':lab_dataset}),range(3)))
                assert all(r.status_code==201 for r in lab_experiments),[r.text for r in lab_experiments]
                assert len({r.json()['id'] for r in lab_experiments})==1
                lab_id=lab_experiments[0].json()['id']
                entered.clear();release.clear();calls.clear()
                class LabProvider:
                    def propose(self,evidence,profile):
                        calls.append(1);entered.set();assert release.wait(10)
                        return dict(inference_spec('proposals',profile),proposals=[],seconds=1,tokens=1)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first=pool.submit(process_ai,app.state.engine,settings,LabProvider())
                    assert entered.wait(10)
                    assert process_ai(app.state.engine,settings,LabProvider()) is False
                    release.set();assert first.result()
                assert len(calls)==1
                assert process_ai(app.state.engine,settings,LabProvider())
                lab=client.get('/api/v1/lab/experiments/'+lab_id).json()
                for run in lab['runs']:
                    url=f'/api/v1/lab/experiments/{lab_id}/runs/{run["id"]}/annotations'
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        annotations=list(pool.map(lambda _:client.post(url,json=dict(revision=0,verdict='uncertain',reason='Synthetic concurrency check')),range(2)))
                    assert sorted(r.status_code for r in annotations)==[201,409]
                assert client.post('/api/v1/lab/experiments/'+lab_id+'/reveal').status_code==200
                print('AI Lab PostgreSQL PASS: concurrent dataset/experiment deduplication, global GPU lease, annotation revision fencing and reveal.')
                batch_args=dict(job_id=receipt['job_id'],page_start=1,page_end=1,profile='qwen4')
                batch_preview=client.get('/api/v1/ai/batches/preview',params=batch_args)
                assert batch_preview.status_code==200,batch_preview.text
                batch_args['plan_hash']=batch_preview.json()['plan_hash']
                with ThreadPoolExecutor(max_workers=3) as pool:
                    batches=list(pool.map(lambda _:client.post('/api/v1/ai/batches',json=batch_args),range(3)))
                assert all(r.status_code==201 for r in batches),[r.text for r in batches]
                assert len({r.json()['id'] for r in batches})==1
                batch_id=batches[0].json()['id'];batch_url='/api/v1/ai/batches/'+batch_id
                entered.clear();release.clear();calls.clear()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first=pool.submit(process_ai,app.state.engine,settings,Provider())
                    assert entered.wait(10)
                    assert client.post(batch_url+'/cancel').status_code==200
                    assert client.post(batch_url+'/retry').status_code==409
                    assert process_ai(app.state.engine,settings,Provider()) is False
                    release.set();assert first.result()
                result=client.get(batch_url).json()
                assert result['counts']=={'cancelled':1} and len(calls)==1
                assert client.post(batch_url+'/retry').status_code==200
                assert process_ai(app.state.engine,settings,Provider())
                assert client.get(batch_url).json()['state']=='succeeded'
                print('AI batch PostgreSQL PASS: concurrent atomic creation, cancellation lease, no overlapping provider and retry.')
                from goldenstock.monitoring import process_monitor
                from goldenstock.models import MonitorSource,MonitorEvent,SiteNotification
                assert client.put('/api/v1/favorites/jpm').status_code==200
                with Session(app.state.engine) as db,db.begin():
                    for source in db.scalars(select(MonitorSource)): source.next_check=1e12
                    db.get(MonitorSource,'jpm-facts').next_check=0
                monitor_calls=[];monitor_value=[100]
                def monitor_fetch(company,contact,kind):
                    monitor_calls.append(1)
                    payload={'cik':19617,'facts':{'us-gaap':{'Assets':{'units':{'USD':[dict(val=monitor_value[0],end='2025-12-31',filed='2026-02-01',accn='0000019617-26-000001',form='10-K')]}}}}}
                    return 'https://data.sec.gov/synthetic',json.dumps(payload).encode(),payload
                def monitor_once(_): return process_monitor(app.state.engine,settings,monitor_fetch,1800000000)
                with ThreadPoolExecutor(max_workers=3) as pool: monitor_results=list(pool.map(monitor_once,range(3)))
                assert monitor_results.count(True)==1 and len(monitor_calls)==1
                assert client.get('/api/v1/notifications').json()['items']==[]
                monitor_value[0]=110
                with Session(app.state.engine) as db,db.begin(): db.get(MonitorSource,'jpm-facts').next_check=0
                with ThreadPoolExecutor(max_workers=3) as pool: monitor_results=list(pool.map(monitor_once,range(3)))
                assert monitor_results.count(True)==1 and len(monitor_calls)==2
                feed=client.get('/api/v1/notifications').json()['items'];assert len(feed)==1 and feed[0]['kind']=='possible_revision'
                history_url='/api/v1/monitoring/jpm-facts/history/'+feed[0]['item_key']
                versions=client.get(history_url).json()['items']
                assert [v['value']['value'] for v in versions]==['110','100'] and [v['revision'] for v in versions]==[2,1]
                assert feed[0]['comparison']['percent']=='10.00' and feed[0]['comparison']['significant']
                with Session(app.state.engine) as db,db.begin(): db.get(MonitorSource,'jpm-facts').next_check=0
                with ThreadPoolExecutor(max_workers=3) as pool: repeated=list(pool.map(monitor_once,range(3)))
                assert repeated.count(True)==1 and client.get(history_url).json()['items']==versions
                with ThreadPoolExecutor(max_workers=3) as pool:
                    read_results=list(pool.map(lambda _:client.post('/api/v1/notifications/'+feed[0]['id']+'/read'),range(3)))
                assert all(r.status_code==200 for r in read_results) and len({r.json()['read_at'] for r in read_results})==1
                print('Monitoring PostgreSQL PASS: one concurrent source request, immutable source history, exact comparison, atomic delivery and idempotent private read state.')
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
                check_template_publications(app,client,password)
                print('PostgreSQL integration PASS: migrations, concurrent upload/fact/review/snapshot/AI deduplication, single GPU task, single successor, crash recovery and stale-worker fencing.')
                check_pdf_resume(app,client)
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

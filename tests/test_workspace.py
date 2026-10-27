"""Tenant boundaries are checked through public HTTP endpoints, not only helpers."""
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.api import create_app
from goldenstock.auth import hash_password
from goldenstock.config import Settings, get_settings
from goldenstock.models import Organization, User, AuditEvent

PASSWORD = 'Synthetic-test-password-123'


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    url = f'sqlite:///{tmp_path / "workspace.db"}'
    monkeypatch.setenv('GS_DATABASE_URL', url)
    get_settings.cache_clear()
    command.upgrade(Config('alembic.ini'), 'head')
    app = create_app(Settings(_env_file=None, database_url=url, data_dir=tmp_path, public_url='http://testserver'))
    with Session(app.state.engine) as db, db.begin():
        org, other = Organization(name='Fund A'), Organization(name='Fund B')
        db.add_all([org, other]); db.flush()
        hashed = hash_password(PASSWORD)
        for login, tenant, admin in [('alice', org.id, True), ('bob', org.id, False), ('eve', other.id, True)]:
            db.add(User(login=login, org_id=tenant, password_hash=hashed, account_admin=admin))
    clients = []
    def connect(login='alice'):
        client = TestClient(app)
        clients.append(client)
        client.headers['origin'] = 'http://testserver'
        result = client.post('/api/v1/auth/login', json={'login': login, 'password': PASSWORD})
        assert result.status_code == 200, result.text
        client.headers['x-csrf-token'] = result.json()['csrf']
        return client
    yield app, connect
    for client in clients:
        client.close()
    app.state.engine.dispose()
    get_settings.cache_clear()


def test_model_privacy_sharing_and_audit(workspace):
    app, connect = workspace
    a, b, e = connect(), connect('bob'), connect('eve')
    model = a.post('/api/v1/models', json={'title': 'Private forecast'}).json()
    key = model['id']
    for client in (b, e):
        assert client.get(f'/api/v1/models/{key}').status_code == 404
        assert client.get('/api/v1/models?q=Private').json() == []
    assert a.patch(f'/api/v1/models/{key}/visibility', json={'shared': True, 'revision': 1}).status_code == 200
    assert b.get(f'/api/v1/models/{key}').status_code == 200
    assert e.get(f'/api/v1/models/{key}').status_code == 404
    assert b.patch(f'/api/v1/models/{key}/visibility', json={'shared': False, 'revision': 2}).status_code == 404
    assert a.patch(f'/api/v1/models/{key}/visibility', json={'shared': False, 'revision': 1}).status_code == 409
    assert a.patch(f'/api/v1/models/{key}/visibility', json={'shared': False, 'revision': 2}).status_code == 200
    assert b.get(f'/api/v1/models/{key}').status_code == 404
    with Session(app.state.engine) as db:
        assert len(list(db.scalars(select(AuditEvent).where(AuditEvent.action == 'model.visibility')))) == 2


def test_admin_is_not_financial_superuser_and_revokes_sessions(workspace):
    _, connect = workspace
    a, b, e = connect(), connect('bob'), connect('eve')
    model = b.post('/api/v1/models', json={'title': 'Bob only'}).json()
    assert a.get('/api/v1/models/'+model['id']).status_code == 404
    assert b.get('/api/v1/users').status_code == 403
    bob = b.get('/api/v1/auth/me').json()
    assert e.patch('/api/v1/users/'+bob['id'], json={'active': False}).status_code == 404
    assert a.patch('/api/v1/users/'+bob['id'], json={'active': False}).status_code == 200
    assert b.get('/api/v1/auth/me').status_code == 401
    assert b.post('/api/v1/auth/login', json={'login':'bob','password':PASSWORD}).status_code == 401


def test_csrf_logout_and_fifteen_accounts(workspace):
    app, connect = workspace
    a = connect()
    a.headers['x-csrf-token'] = 'bad'
    assert a.post('/api/v1/models', json={'title':'blocked'}).status_code == 403
    a.headers['x-csrf-token'] = a.get('/api/v1/auth/me').json()['csrf']
    a.headers['origin'] = 'https://attacker.invalid'
    assert a.post('/api/v1/models', json={'title':'blocked'}).status_code == 403
    a.headers['origin'] = 'http://testserver'
    for n in range(13):
        assert a.post('/api/v1/users', json={'login':f'analyst{n}', 'password':PASSWORD}).status_code == 201
    assert len(a.get('/api/v1/users').json()) == 15
    for n in range(13):
        assert connect(f'analyst{n}').get('/api/v1/auth/me').status_code == 200
    assert a.post('/api/v1/auth/logout').status_code == 200
    assert a.get('/api/v1/models').status_code == 401


def test_favorites_and_honest_missing_data(workspace):
    _, connect = workspace
    a, b = connect(), connect('bob')
    assert a.get('/api/v1/companies?favorites=true').json() == []
    assert a.put('/api/v1/favorites/sber').status_code == 200
    assert a.put('/api/v1/favorites/sber').status_code == 200
    selected = a.get('/api/v1/companies?favorites=true').json()
    assert len(selected) == 1
    assert selected[0]['freshness'] == 'missing'
    assert selected[0]['last_calculation'] == 'not_run'
    assert selected[0]['source_url'] is None
    assert b.get('/api/v1/companies?favorites=true').json() == []
    assert a.delete('/api/v1/favorites/sber').status_code == 200
    assert a.get('/api/v1/companies?favorites=true').json() == []
    assert a.put('/api/v1/favorites/unknown').status_code == 404
    assert len(a.get('/api/v1/companies?q=HSBC').json()) == 1
    from goldenstock.companies import company_dict
    from goldenstock.models import Company
    assert company_dict(Company(id='old', name='Old', identifier='', candidate=False, source_checked=1))['freshness'] == 'stale'


def upload(client, key='test-key-0001', content=b'%PDF-1.4\nsynthetic fixture\n%%EOF', name='report.pdf', document_id=''):
    return client.post('/api/v1/documents',headers={'Idempotency-Key':key},
        data={'company_id':'sber','document_id':document_id},files={'file':(name,content,'application/octet-stream')})


def test_public_sources_do_not_expose_private_evidence(workspace):
    app, connect = workspace
    a, e = connect(), connect('eve')
    assert TestClient(app).get('/api/v1/sources').status_code == 401
    receipt = upload(a, name='private-finances.pdf').json()
    result = a.get('/api/v1/sources')
    assert result.json() == e.get('/api/v1/sources').json()
    assert len(result.json()) == 9
    assert receipt['version_id'] not in result.text
    assert 'private-finances' not in result.text
    assert e.get('/api/v1/documents').json() == []
    assert a.post('/api/v1/sources', json={'url':'http://localhost'}).status_code == 405


def test_source_identity_gaps_and_report_freshness(workspace):
    _, connect = workspace
    client = connect()
    assert client.get('/api/v1/sources?company_id=T-Bank').status_code == 404
    assert client.get('/api/v1/sources/not-a-source').status_code == 404
    assert {s['id'] for s in client.get('/api/v1/sources?company_id=tinkoff').json()} == {'t-results','t-disclosure'}
    sber = client.get('/api/v1/sources/sber-ir').json()
    assert sber['availability'] == 'unavailable_to_verifier'
    assert sber['english'] == 'unverified'
    for item in client.get('/api/v1/sources').json():
        assert item['auto_fetch_enabled'] is False
        assert item['financial_data_status'] == 'not_ingested'
        assert item['coverage_status'] == 'incomplete'
    companies = client.get('/api/v1/companies').json()
    assert all(not c['candidate'] and c['freshness']=='missing' for c in companies)
    assert next(c for c in companies if c['id']=='tinkoff')['name'] == 'T-Technologies'


def test_source_review_expiry_does_not_change_availability():
    from datetime import date
    from goldenstock.sources import SOURCES, source_dict
    source = SOURCES[0]
    assert source_dict(source, date(2026,10,22))['review_freshness'] == 'current'
    assert source_dict(source, date(2027,2,1))['review_freshness'] == 'stale'
    assert source_dict(source, date(2026,1,1))['review_freshness'] == 'stale'
    assert source_dict(source, date(2027,2,1))['availability'] == 'unavailable_to_verifier'


@pytest.mark.parametrize('url', ['http://www.sec.gov/', 'https://www.sec.gov.evil/',
    'https://user@www.sec.gov/', 'https://127.0.0.1/', 'javascript:alert(1)'])
def test_source_registry_rejects_unreviewed_urls(url):
    from goldenstock.sources import validate_url
    with pytest.raises(ValueError):
        validate_url(url)


def test_source_page_shows_gaps_and_safe_links(workspace):
    from goldenstock.ui import mount_ui
    app, connect = workspace
    mount_ui(app)
    client = connect()
    response = client.get('/sources?company_id=sber')
    assert response.status_code == 200
    assert 'unavailable to verifier' in response.text
    assert 'English: unverified' in response.text
    assert 'No reports ingested' in response.text
    assert client.get('/sources?company_id=T-Bank').status_code == 404
    assert '/sources?company_id=sber' in client.get('/company/sber').text


def test_original_idempotency_versions_and_cross_tenant_access(workspace):
    _,connect=workspace
    a,b,e=connect(),connect('bob'),connect('eve')
    first=upload(a).json()
    assert upload(a).json()==first
    assert upload(a,content=b'%PDF-1.4\nchanged').status_code==409
    second=upload(a,key='test-key-0002',content=b'%PDF-1.4\nnew version',document_id=first['document_id']).json()
    assert second['number']==2
    url=f'/api/v1/documents/{first["document_id"]}/versions/{first["version_id"]}/download'
    assert a.get(url).content==b'%PDF-1.4\nsynthetic fixture\n%%EOF'
    for client in (b,e):
        assert client.get(url).status_code==404
        assert client.get('/api/v1/documents?q=report').json()==[]
        assert client.get('/api/v1/jobs/'+first['job_id']).status_code==404
        assert client.post('/api/v1/jobs/'+first['job_id']+'/retry').status_code==404
        assert upload(client,document_id=first['document_id']).status_code==404
    foreign=upload(e).json()
    assert foreign['version_id']!=first['version_id']
    assert a.get(f'/api/v1/documents/{first["document_id"]}/versions/{foreign["version_id"]}/download').status_code==404


def test_upload_type_size_path_and_archive_limits(workspace):
    import io,zipfile
    app,connect=workspace
    client=connect()
    assert upload(client,name='../escape.pdf').status_code==422
    assert upload(client,name='report.exe').status_code==422
    assert upload(client,content=b'MZnot a PDF').status_code==422
    assert upload(client,content=b'').status_code==413
    app.state.settings.max_file_bytes=20
    assert upload(client,content=b'%PDF-'+b'x'*30).status_code==413
    app.state.settings.max_file_bytes=50*1024*1024
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types/>')
        archive.writestr('xl/workbook.xml','<workbook/>')
        archive.writestr('xl/vbaProject.bin',b'unsafe')
    assert upload(client,name='macro.xlsx',content=output.getvalue()).status_code==422
    assert client.post('/api/v1/documents',headers={'Content-Length':str(60*1024*1024)}).status_code==413


def test_worker_lease_recovery_fencing_retry_and_integrity(workspace):
    from goldenstock.jobs import claim,execute
    from goldenstock.models import Job,DocumentVersion
    from goldenstock.storage import FileStore
    app,connect=workspace
    a=connect()
    result=upload(a).json()
    first=claim(app.state.engine,now=100)
    assert first
    assert claim(app.state.engine,now=101) is None
    replacement=claim(app.state.engine,now=161)
    assert replacement and replacement[1]!=first[1]
    execute(app.state.engine,app.state.settings,first,now=162)
    assert a.get('/api/v1/jobs/'+result['job_id']).json()['state']=='running'
    execute(app.state.engine,app.state.settings,replacement,now=163)
    assert a.get('/api/v1/jobs/'+result['job_id']).json()['state']=='succeeded'
    assert claim(app.state.engine,now=999) is None
    other=upload(a,key='missing-0001',content=b'%PDF-1.4\nanother').json()
    with Session(app.state.engine) as db:
        v=db.get(DocumentVersion,other['version_id'])
        path=FileStore(app.state.settings.data_dir).path(v.blob_key)
    original=path.read_bytes()
    path.unlink()
    for now in (1000,1100,1200):
        execute(app.state.engine,app.state.settings,claim(app.state.engine,now),now)
    state=a.get('/api/v1/jobs/'+other['job_id']).json()
    assert state['state']=='failed' and state['attempts']==3
    assert len(state['history'])==7
    path.write_bytes(original)
    assert a.post('/api/v1/jobs/'+other['job_id']+'/retry').status_code==200
    execute(app.state.engine,app.state.settings,claim(app.state.engine,1300),1300)
    assert a.get('/api/v1/jobs/'+other['job_id']).json()['state']=='succeeded'


def test_worker_rechecks_revoked_actor(workspace):
    from goldenstock.jobs import claim,execute
    app,connect=workspace
    a,b=connect(),connect('bob')
    result=upload(b).json()
    leased=claim(app.state.engine)
    bob=b.get('/api/v1/auth/me').json()
    a.patch('/api/v1/users/'+bob['id'],json={'active':False})
    execute(app.state.engine,app.state.settings,leased)
    from goldenstock.models import Job
    with Session(app.state.engine) as db:
        job=db.get(Job,result['job_id'])
        assert job.state=='failed' and job.error_code=='access_revoked'


def test_session_expiry_and_cookie_flags(workspace):
    from goldenstock.models import LoginSession
    app,connect=workspace
    a=connect()
    response=a.post('/api/v1/auth/login',json={'login':'alice','password':PASSWORD})
    cookie=response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie
    with Session(app.state.engine) as db,db.begin():
        for session in db.scalars(select(LoginSession)):
            session.expires=1
    assert a.get('/api/v1/auth/me').status_code==401


def test_tampered_original_and_dead_worker_attempt_cap(workspace):
    from goldenstock.jobs import claim,execute
    from goldenstock.models import DocumentVersion,Job
    from goldenstock.storage import FileStore
    app,connect=workspace
    a=connect()
    result=upload(a).json()
    with Session(app.state.engine) as db:
        v=db.get(DocumentVersion,result['version_id'])
        FileStore(app.state.settings.data_dir).path(v.blob_key).write_bytes(b'changed outside app')
    execute(app.state.engine,app.state.settings,claim(app.state.engine))
    assert a.get('/api/v1/jobs/'+result['job_id']).json()['error_code']=='checksum_mismatch'
    dead=upload(a,key='dead-worker-key',content=b'%PDF-1.4\nworker crash').json()
    for now in (100,161,222):
        assert claim(app.state.engine,now)
    assert claim(app.state.engine,283) is None
    with Session(app.state.engine) as db:
        assert db.get(Job,dead['job_id']).state=='failed'


def test_ui_requires_login_and_escapes_names(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace
    mount_ui(app)
    with TestClient(app) as guest:
        assert guest.get('/',follow_redirects=False).status_code==303
        assert guest.get('/files',follow_redirects=False).status_code==303
    a=connect()
    a.post('/api/v1/models',json={'title':'<script>alert(1)</script>'})
    response=a.get('/models')
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in response.text
    assert '<script>alert(1)</script>' not in response.text
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']


def test_valid_office_archive_and_throttling(workspace):
    import io,zipfile
    from goldenstock.accounts import LoginLimiter
    from fastapi import HTTPException
    _,connect=workspace
    a=connect()
    for suffix,part in [('xlsx','xl/workbook.xml'),('pptx','ppt/presentation.xml')]:
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr('[Content_Types].xml','<Types/>')
            archive.writestr(part,'<root/>')
        assert upload(a,key='valid-office-'+suffix,name='file.'+suffix,content=buffer.getvalue()).status_code==201
    limiter=LoginLimiter()
    for _ in range(30):
        limiter.check('client')
    with pytest.raises(HTTPException) as result:
        limiter.check('client')
    assert result.value.status_code==429

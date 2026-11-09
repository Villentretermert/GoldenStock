"""Publication boundaries, fanout, immutable copies and private drafts through HTTP."""
import json
from pathlib import Path
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from test_workspace import workspace
from test_templates import DEMO,post,modify
from test_calculations import payload,run
from goldenstock.models import User,ModelTemplate,TemplateVersion,TemplatePublication,TemplateNotification


def share(client,tid,shared=True):
    revision=client.get('/api/v1/templates/'+tid).json()['revision']
    return client.patch('/api/v1/templates/'+tid+'/visibility',json=dict(shared=shared,revision=revision))


def feed(client,query=''):
    response=client.get('/api/v1/template-updates'+query);assert response.status_code==200,response.text
    return response.json()['items']


def test_publication_all_active_fund_readers_and_private_inputs(workspace):
    app,connect=workspace;a=connect();b=connect('bob');e=connect('eve')
    with Session(app.state.engine) as db,db.begin():
        author=db.scalar(select(User).where(User.login=='alice'))
        db.add(User(org_id=author.org_id,login='never-opened',password_hash=author.password_hash))
        db.add(User(org_id=author.org_id,login='inactive',password_hash=author.password_hash,active=False))
    def secrets(book): book['Model']['B11']=987654321;book['Model']['A22']='SECRET personal note'
    version=post(a,modify(secrets)).json();tid=version['template_id']
    assert feed(a)==feed(b)==feed(e)==[]
    planned=a.get('/api/v1/templates/'+tid).json()['publication_preview']
    assert not planned['already_published'] and planned['number']==1
    assert share(a,tid).status_code==200
    c=connect('never-opened')
    for client in (a,b,c):
        items=feed(client);assert len(items)==1 and items[0]['version_id']==version['id']
        assert '987654321' not in json.dumps(items) and 'SECRET' not in json.dumps(items)
        assert client.get('/api/v1/notifications/count').json()['templates_unread']==1
    assert feed(e)==[] and e.get('/api/v1/templates/'+tid).status_code==404
    assert b.get(f'/api/v1/templates/{tid}/versions/{version["id"]}/original').status_code==404
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(TemplateNotification))==3
    assert share(a,tid).status_code==200 and len(feed(b))==1


def test_private_drafts_publication_diff_revocation_and_frozen_copy(workspace):
    _,connect=workspace;a=connect();b=connect('bob')
    v1=post(a).json();tid=v1['template_id'];share(a,tid).raise_for_status()
    clone=b.post('/api/v1/templates/'+tid+'/copy').json()
    saved=b.get('/api/v1/templates/'+clone['id']).json()
    calculation=run(b,payload(v1));assert calculation.status_code==201,calculation.text
    v2=post(a,template_id=tid,key='unpublished-two').json()
    assert feed(b)==[] and b.get('/api/v1/notifications/count').json()['unread_count']==0
    def changed(book):
        book['Model']['B7']='=B11*(1+B12+B12)';book['GS_Map']['F2']='Changed synthetic definition'
    v3=post(a,modify(changed),template_id=tid,key='published-three').json()
    preview=a.get('/api/v1/templates/'+tid).json()['publication_preview']
    assert preview['previous_number']==1 and any('formula' in s for s in preview['changes'])
    share(a,tid).raise_for_status()
    items=feed(b);assert [i['detail']['number'] for i in items]==[3,1]
    assert b.get('/api/v1/templates/'+tid).json()['versions'][0]['id']==v3['id']
    assert len(b.get('/api/v1/templates/'+tid).json()['versions'])==2
    assert b.get(f'/api/v1/templates/{tid}/versions/{v2["id"]}/structure').status_code==404
    assert run(b,payload(v2),key='private-calculation').status_code==404
    assert b.get('/api/v1/templates/'+clone['id']).json()==saved
    assert b.get('/api/v1/calculations/'+calculation.json()['id']).status_code==200
    assert len(feed(b,'?offset=1'))==1 and feed(b,'?offset=2')==[]
    share(a,tid,False).raise_for_status()
    assert b.post('/api/v1/template-updates/'+items[0]['id']+'/read').status_code==404
    assert feed(b)==[] and len(feed(a))==2
    share(a,tid).raise_for_status();assert len(feed(b))==2


def test_read_state_access_csrf_and_disabled_user(workspace):
    _,connect=workspace;a=connect();b=connect('bob');e=connect('eve')
    version=post(a).json();share(a,version['template_id']).raise_for_status()
    own=feed(b)[0];url='/api/v1/template-updates/'+own['id']+'/read'
    assert a.post(url).status_code==404 and e.post(url).status_code==404
    csrf=b.headers['x-csrf-token'];b.headers['x-csrf-token']='wrong'
    assert b.post(url).status_code==403;b.headers['x-csrf-token']=csrf
    result=b.post(url).json();assert b.post(url).json()==result
    assert feed(b,'?unread=true')==[] and len(feed(a,'?unread=true'))==1
    assert b.get('/api/v1/notifications/count').json()['unread_count']==0
    assert b.get('/api/v1/template-updates?offset=-1').status_code==422
    bid=b.get('/api/v1/auth/me').json()['id'];a.patch('/api/v1/users/'+bid,json=dict(active=False)).raise_for_status()
    assert b.get('/api/v1/template-updates').status_code==401 and b.post(url).status_code==401


def test_publication_rolls_back_and_requires_intact_structure(workspace,monkeypatch):
    import goldenstock.template_publications as module
    from goldenstock.storage import FileStore
    app,connect=workspace;a=connect();v=post(a).json();tid=v['template_id']
    audit=module.audit
    def crash(*args): raise RuntimeError('Synthetic publication crash')
    monkeypatch.setattr(module,'audit',crash)
    with pytest.raises(RuntimeError): share(a,tid)
    assert not a.get('/api/v1/templates/'+tid).json()['shared'] and feed(a)==[]
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(TemplatePublication))==0
        path=FileStore(app.state.settings.data_dir).path(db.get(TemplateVersion,v['id']).clean_key)
    monkeypatch.setattr(module,'audit',audit);original=path.read_bytes();path.write_bytes(b'broken')
    assert share(a,tid).status_code==409 and feed(a)==[]
    path.write_bytes(original);share(a,tid).raise_for_status()
    with Session(app.state.engine) as db,db.begin(): db.scalar(select(TemplatePublication)).payload='{}'
    assert a.get('/api/v1/template-updates').status_code==409


def test_legacy_shared_versions_migrate_without_notifications(workspace):
    from alembic import command
    from alembic.config import Config
    app,connect=workspace;a=connect();b=connect('bob')
    v1=post(a).json();v2=post(a,template_id=v1['template_id'],key='legacy-second').json()
    private=post(a,key='private-template').json()
    command.downgrade(Config('alembic.ini'),'0020')
    with Session(app.state.engine) as db,db.begin(): db.get(ModelTemplate,v1['template_id']).shared=True
    command.upgrade(Config('alembic.ini'),'head')
    data=b.get('/api/v1/templates/'+v1['template_id']).json()
    assert len(data['versions'])==2 and all(v['published'] for v in data['versions'])
    assert b.get('/api/v1/templates/'+private['template_id']).status_code==404
    assert feed(a)==feed(b)==[]
    with Session(app.state.engine) as db:
        assert all(r.legacy for r in db.scalars(select(TemplatePublication)))
    share(a,v1['template_id']).raise_for_status();assert feed(a)==[]


def test_publication_ui_and_evidence(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace;mount_ui(app);a=connect();b=connect('bob')
    v=post(a).json();tid=v['template_id'];preview=a.get('/templates/'+tid).text
    assert 'Publication preview' in preview and 'One site update' in preview
    share(a,tid).raise_for_status()
    page=b.get('/updates?category=models').text
    assert 'First publication: 7 mapped fields.' in page and 'Open published version' in page
    assert 'Download private original' not in b.get('/templates/'+tid).text
    folder=Path('.build-template-publications');folder.mkdir(exist_ok=True)
    (folder/'preview.html').write_text(preview,encoding='utf-8')
    (folder/'updates.html').write_text(page,encoding='utf-8')
    (folder/'version.html').write_text(b.get('/templates/'+tid).text,encoding='utf-8')
    (folder/'receipt.json').write_text(json.dumps(dict(template_id=tid,version_id=v['id'],notification_id=feed(b)[0]['id'])),encoding='utf-8')
    share(a,tid,False).raise_for_status()
    assert 'Synthetic five-year template' not in b.get('/updates?category=models').text

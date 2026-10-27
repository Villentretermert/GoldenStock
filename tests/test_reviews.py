from test_workspace import workspace
from test_normalization import seed, context


def fact(client, receipt, **changes):
    response=client.post('/api/v1/facts',json=context(job_id=receipt['job_id'],**changes))
    assert response.status_code==201,response.text
    return response.json()['id']


def decide(client,fid,decision='accepted',revision=0,note='Checked original and context'):
    return client.post(f'/api/v1/facts/{fid}/reviews',json=dict(expected_revision=revision,decision=decision,note=note))


def state(client):
    return client.get('/api/v1/review-state?company_id=sber').json()


def save(client,digest=None):
    return client.post('/api/v1/input-snapshots',json=dict(company_id='sber',title='Checked inputs',expected_state_hash=digest or state(client)['state_hash']))


def test_blockers_exclusion_snapshot_and_stale(workspace):
    app,connect=workspace;client=connect();receipt=seed(client,app)
    first=fact(client,receipt);second=fact(client,receipt,item_index=1,number_text='3')
    assert save(client).status_code==409
    assert decide(client,first).status_code==201
    assert decide(client,second).status_code==201
    assert state(client)['blocker_count']==1
    assert save(client).status_code==409
    assert decide(client,second,'rejected',1,'Incorrect source selection').status_code==201
    assert state(client)['ready']
    saved=save(client);assert saved.status_code==201,saved.text
    sid=saved.json()['id'];assert save(client).json()['id']==sid
    original=client.get('/api/v1/input-snapshots/'+sid).json()
    assert original['eligible_for_future_calculation']
    assert original['snapshot']['facts'][0]['review']['revision']==1
    assert original['snapshot']['excluded'][0]['id']==second
    digest=state(client)['state_hash']
    assert decide(client,first,'unreviewed',1).status_code==201
    assert save(client,digest).status_code==409
    stale=client.get('/api/v1/input-snapshots/'+sid).json()
    assert not stale['current'] and not stale['eligible_for_future_calculation']
    assert stale['snapshot']==original['snapshot']


def test_review_revision_privacy_csrf_and_correction(workspace):
    app,connect=workspace;client=connect();receipt=seed(client,app);fid=fact(client,receipt)
    assert decide(client,fid).status_code==201
    assert decide(client,fid).status_code==409
    sid=save(client).json()['id']
    for other in (connect('bob'),connect('eve')):
        assert decide(other,fid).status_code==404
        assert other.get(f'/api/v1/facts/{fid}/reviews').status_code==404
        assert other.get('/api/v1/input-snapshots/'+sid).status_code==404
        assert other.get('/api/v1/input-snapshots?company_id=sber').json()==[]
        assert state(other)['facts']==[]
    assert client.post(f'/api/v1/facts/{fid}/reviews',headers={'x-csrf-token':'bad'},json=dict(expected_revision=1,decision='rejected',note='Wrong')).status_code==403
    updated=fact(client,receipt,supersedes=fid,scale='thousands')
    assert decide(client,fid,revision=1).status_code==409
    assert client.get('/api/v1/facts/'+updated).json()['review_status']=='unreviewed'
    assert not client.get('/api/v1/input-snapshots/'+sid).json()['current']
    assert save(client).status_code==409


def test_warnings_preserved_and_empty_set_blocked(workspace):
    app,connect=workspace;client=connect();receipt=seed(client,app)
    fid=fact(client,receipt,item_index=1,number_text='3')
    assert decide(client,fid,note='  ').status_code==422
    assert decide(client,fid).status_code==201
    sid=save(client).json()['id']
    assert client.get('/api/v1/input-snapshots/'+sid).json()['snapshot']['facts'][0]['warnings']==['ocr_requires_review']
    assert decide(client,fid,'rejected',1).status_code==201
    assert not state(client)['ready'] and save(client).status_code==409


def test_review_ui_evidence_and_escaping(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace;mount_ui(app);client=connect();receipt=seed(client,app);fid=fact(client,receipt)
    assert decide(client,fid,note='<script>alert(1)</script>').status_code==201
    response=client.get('/review/sber');assert response.status_code==200,response.text
    assert 'Mapped fact' in response.text and 'Download original' in response.text
    assert '&lt;script&gt;' in response.text and '<script>alert(1)</script>' not in response.text

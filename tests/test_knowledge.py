from test_workspace import workspace
from test_normalization import seed,context
from test_reviews import decide
from goldenstock.ai_runs import process_ai


def test_retrieval_pack_summary_and_stale(workspace):
    app,connect=workspace;a=connect();receipt=seed(a,app)
    fid=a.post('/api/v1/facts',json=context(job_id=receipt['job_id'])).json()['id']
    assert a.get('/api/v1/knowledge/sber/export').json()['facts']==[]
    assert a.post('/api/v1/ai/summaries',json={'company_id':'sber'}).status_code==409
    decide(a,fid)
    pack=a.get('/api/v1/knowledge/sber/export').json()
    assert pack['facts'][0]['review']['decision']=='accepted'
    found=a.get('/api/v1/knowledge/sber/search?q=profit').json()
    assert found['evidence'][0]['id']==fid
    for other in (connect('bob'),connect('eve')):
        assert other.get('/api/v1/knowledge/sber/export').json()['facts']==[]
        assert other.get('/api/v1/knowledge/sber/search?q=profit').json()['evidence']==[]
    response=a.post('/api/v1/ai/summaries',json={'company_id':'sber'})
    assert response.status_code==201,response.text
    key=response.json()['id']
    class Fake:
        def summarize(self,evidence,profile):
            assert evidence[0]['id']==fid
            return dict(claims=[dict(text='Reported profit',evidence_id=fid,quote=evidence[0]['text'])],gaps=[],status='unreviewed')
    process_ai(app.state.engine,app.state.settings,Fake())
    assert a.get('/api/v1/ai/runs/'+key).json()['current']
    decide(a,fid,'unreviewed',1)
    assert not a.get('/api/v1/ai/runs/'+key).json()['current']


def test_ai_ui_escapes_output(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace;mount_ui(app);a=connect();receipt=seed(a,app)
    response=a.get('/ai/sber')
    assert response.status_code==200 and 'Suggest metrics' in response.text
    key=a.post('/api/v1/ai/proposals',json={'job_id':receipt['job_id']}).json()['id']
    assert a.get('/ai-run/'+key).status_code==200

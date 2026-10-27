import json
from datetime import date
import httpx
import pytest
from fastapi import HTTPException
from test_workspace import workspace
from goldenstock.public_sources import fetch,evidence
from goldenstock.models import PublicSnapshot
from goldenstock.ai_runs import process_ai


def fixture():
    return dict(cik=19617,facts={'us-gaap':{'Assets':{'label':'Assets','units':{'USD':[dict(val=100,end=f'{date.today().year-1}-12-31',form='10-K',filed=f'{date.today().year}-02-01',accn='synthetic')]}}}})


def test_fixed_connector_contact_and_identity(monkeypatch):
    monkeypatch.setattr('goldenstock.public_sources.time.sleep',lambda _:None)
    def handle(request):
        assert request.url.host=='data.sec.gov'
        assert request.url.path.endswith('CIK0000019617.json')
        assert request.headers['user-agent']=='GoldenStock pilot qa@example.test'
        return httpx.Response(200,json=fixture())
    _,raw,data=fetch('jpm','qa@example.test',httpx.MockTransport(handle))
    assert data['cik']==19617 and raw
    for company,contact in [('sber','qa@example.test'),('jpm',''),('http://evil','qa@example.test')]:
        with pytest.raises(HTTPException): fetch(company,contact,httpx.MockTransport(handle))
    with pytest.raises(HTTPException): fetch('jpm','qa@example.test',httpx.MockTransport(lambda _:httpx.Response(302,headers={'location':'http://localhost'})))
    with pytest.raises(HTTPException): fetch('jpm','qa@example.test',httpx.MockTransport(lambda _:httpx.Response(200,json={'cik':5,'facts':{}})))


def test_public_summary_cached_and_cited(workspace,monkeypatch):
    app,connect=workspace;a=connect();calls=[]
    def fake_fetch(company,contact):
        calls.append(1);data=fixture();return 'https://data.sec.gov/synthetic',json.dumps(data).encode(),data
    monkeypatch.setattr('goldenstock.public_sources.fetch',fake_fetch)
    response=a.post('/api/v1/ai/public-summaries',json={'company_id':'jpm'})
    assert response.status_code==201,response.text
    key=response.json()['id']
    assert a.post('/api/v1/ai/public-summaries',json={'company_id':'jpm'}).json()['id']==key
    assert len(calls)==1
    class Fake:
        def summarize(self,sources,profile):
            assert sources[0]['json_path'].startswith('/facts/us-gaap/Assets/')
            return dict(claims=[dict(text='Reported assets',quote=sources[0]['text'],evidence_id=sources[0]['id'])],gaps=[])
    process_ai(app.state.engine,app.state.settings,Fake())
    result=a.get('/api/v1/ai/runs/'+key).json()
    assert result['state']=='succeeded'
    # Raw public data is shared, private analysis runs are not.
    b=connect('bob')
    assert b.get('/api/v1/public-snapshots/'+result['snapshot_id']).status_code==200
    assert b.get('/api/v1/public-snapshots/'+result['snapshot_id']+'/download').content==json.dumps(fixture()).encode()
    assert b.get('/api/v1/ai/runs/'+key).status_code==404

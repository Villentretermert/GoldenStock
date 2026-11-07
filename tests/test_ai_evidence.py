import json
import pytest
from sqlalchemy.orm import Session
from goldenstock.ai_evidence import source_window, MAX_EVIDENCE_JSON
from goldenstock.models import Extraction, AIRun
from goldenstock.ai_runs import process_ai
from test_workspace import workspace
from test_normalization import seed


def item(text, page=199):
    return dict(text=text, location={'page': page}, method='native')


@pytest.mark.parametrize('raw', [
    'Assets 312,300 298,001\n' * 700,
    '📊 Ω\tProfit −12,345.67 (9,999.12)\r\n' * 500,
    ('"\\' * 3000) + '\n',
    'x ' * 10000,
])
def test_lossless_bounded_windows(raw):
    items=[item(raw), item(''), item('Final assets 0')]
    cursor=dict(offset=0, text_offset=0); seen=set(); spans={0:[], 2:[]}
    while cursor:
        key=tuple(cursor.values()); assert key not in seen; seen.add(key)
        try:
            window=source_window(items,'v'*32,'s'*64,**cursor)
        except ValueError as exc:
            # One huge token cannot be split safely into an AI request.
            assert raw.startswith('"\\') and 'token exceeds' in str(exc)
            return
        assert len(json.dumps(window['evidence'])) <= MAX_EVIDENCE_JSON
        assert len(window['evidence']) <= 8
        for entry in window['evidence']:
            start,end=entry['source_range']; index=entry['item_index']
            assert entry['text']==items[index]['text'][start:end]
            assert entry['id']=='v'*32+':'+str(index)
            assert start==0 or items[index]['text'][start-1].isspace()
            assert end==len(items[index]['text']) or items[index]['text'][end-1].isspace()
            spans[index].append((start,end,entry['text']))
        cursor=window['next_cursor']
    for index, entries in spans.items():
        assert ''.join(part[2] for part in entries)==items[index]['text']
        assert all(a[1]==b[0] for a,b in zip(entries,entries[1:]))


def test_window_limits_empty_items_and_invalid_cursors():
    items=[item('')]*9+[item('USD 42')]
    first=source_window(items,'v','s')
    assert first['evidence']==[] and first['next_cursor']==dict(offset=8,text_offset=0)
    last=source_window(items,'v','s',**first['next_cursor'])
    assert last['evidence'][0]['item_index']==9 and last['next_cursor'] is None
    for offset,start in ((-1,0),(10,0),(9,7),(9,1),(9,-1)):
        with pytest.raises(ValueError): source_window(items,'v','s',offset,start)


def test_private_preview_queue_and_saved_provenance(workspace):
    from goldenstock.ui import mount_ui
    app,connect=workspace; mount_ui(app); client=connect(); receipt=seed(client,app)
    raw=('Synthetic FY 2025. Group USD millions. <script>test</script>\n'
         +'Assets 312,300 298,001\n'*700)
    with Session(app.state.engine) as db,db.begin():
        db.get(Extraction,receipt['version_id']).payload=json.dumps({'items':[item(raw)]})
    params=dict(job_id=receipt['job_id'],offset=0)
    url='/api/v1/ai/proposal-evidence'
    first=client.get(url,params=params).json()
    cursor=first['next_cursor']; assert cursor['offset']==0 and cursor['text_offset']>0
    assert first['evidence'][0]['source_range'][0]==0
    html=client.get('/ai-evidence',params=params).text
    assert 'Preview next fragment' in html and '&lt;script&gt;test' in html
    assert '<script>test</script>' not in html
    for other in (connect('bob'),connect('eve')):
        assert other.get(url,params=params).status_code==404
        assert other.get('/ai-evidence',params=params).status_code==404
        assert other.post('/api/v1/ai/proposals',json=params|cursor).status_code==404
    assert client.post('/api/v1/ai/proposals',headers={'x-csrf-token':'bad'},json=params).status_code==403
    assert client.post('/api/v1/ai/proposals',json=params|{'evidence':[{'text':'forged'}]}).status_code==422
    assert client.get(url,params=params|{'text_offset':1}).status_code==422
    assert client.get(url,params=params|{'offset':-1}).status_code==422
    key=client.post('/api/v1/ai/proposals',json=params).json()['id']
    assert client.post('/api/v1/ai/proposals',json=params).json()['id']==key
    next_key=client.post('/api/v1/ai/proposals',json=params|cursor).json()['id']
    assert next_key!=key
    saved=client.get('/api/v1/ai/runs/'+key).json()['source_window']
    assert saved['evidence']==first['evidence'] and saved['next_cursor']==cursor
    class Provider:
        def propose(self,evidence,profile):
            assert evidence==first['evidence']
            return dict(proposals=[],status='unreviewed')
    assert process_ai(app.state.engine,app.state.settings,Provider())
    result=client.get('/ai-run/'+key).text
    assert 'Unreviewed output' in result and 'Preview next fragment' in result
    # Legacy runs remain viewable and retain their exact saved evidence.
    with Session(app.state.engine) as db,db.begin():
        row=db.get(AIRun,key)
        row.input=json.dumps(dict(job_id=receipt['job_id'],evidence=[
            dict(id=receipt['version_id']+':0',text='Legacy text',location={'page':1})]))
    assert 'Legacy text' in client.get('/ai-run/'+key).text

"""Server-rendered preview and progress for selected-page AI batches."""
from fastapi import Request,Query
from fastapi.responses import RedirectResponse
from goldenstock.ai_batches import preview,detail


def mount_batch_ui(app):
    from goldenstock.ui import page,e,form,hidden,actor_or_none

    @app.get('/ai-batch-preview')
    def batch_preview(request:Request,job_id:str,page_start:int=Query(1,ge=1,le=1000),
                      page_end:int=Query(1,ge=1,le=1000),profile:str='qwen4'):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=preview(request,job_id,page_start,page_end,profile)
        body=f'<h1>Preview page batch</h1><p>{e(data["filename"])} · original pages {page_start}–{page_end} of {data["total_pages"]}</p><p>{len(data["windows"])} AI requests · {e(data["spec"]["model"])}</p>'
        body+='<div class="notice">All suggestions require review. Only the selected pages are included. Check headings and comparative columns in the original.</div>'
        if data['empty_pages']:
            body+='<p>No extracted text on pages: '+e(', '.join(map(str,data['empty_pages'])))+'. These gaps are retained.</p>'
        body+=f'<p><a href="/ai/{e(data["company_id"])}">Change page range or profile</a></p>'
        if data['windows']:
            fields=''.join(hidden(k,v) for k,v in dict(job_id=job_id,page_start=page_start,page_end=page_end,profile=profile,plan_hash=data['plan_hash']).items())
            body+=form('/api/v1/ai/batches','Start selected-page batch',fields).replace('<form ','<form data-ai-batch="true" ',1)
        for index,window in enumerate(data['windows'],1):
            body+=f'<details class="card"><summary>Request {index} · pages '+e(', '.join(map(str,sorted({x['location']['page'] for x in window['evidence']}))))+'</summary>'
            for entry in window['evidence']:
                start,end=entry['source_range']
                body+=f'<p>Page {entry["location"]["page"]} · characters {start+1}–{end} of {entry["source_length"]}</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{e(entry["text"])}</pre><a href="/normalize/{e(job_id)}/{entry["item_index"]}">Open full source item</a>'
            body+='</details>'
        return page('Preview page batch',body,actor)

    @app.get('/ai-batch/{key}')
    def batch_result(key:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=detail(key,request); m=data['manifest']
        body=f'<h1>Selected-page AI batch</h1><p>{e(m["filename"])} · original pages {m["page_start"]}–{m["page_end"]}</p><p id="batch-progress">{data["completed"]} / {data["total"]} parts finished · {e(data["state"])}</p>'
        body+='<p>Finished parts may contain errors or no suggestions. Results remain unreviewed. Reload for progress.</p>'
        body+=f'<p><a href="/ai-batch/{e(key)}">Refresh batch</a> · <a href="/ai/{e(data["company_id"])}">AI workspace</a></p>'
        if data['counts'].get('queued',0)+data['counts'].get('running',0):
            body+=form('/api/v1/ai/batches/'+key+'/cancel','Cancel pending parts')
        if data['counts'].get('failed',0)+data['counts'].get('cancelled',0):
            body+=form('/api/v1/ai/batches/'+key+'/retry','Retry failed or cancelled parts')
        if m['empty_pages']: body+='<p>No extracted text on pages: '+e(', '.join(map(str,m['empty_pages'])))+'</p>'
        body+='<div class="table-wrap"><table><thead><tr><th>Part</th><th>Pages</th><th>Status</th><th>Suggestions</th></tr></thead><tbody>'
        for r in data['runs']:
            body+=f'<tr><td><a href="/ai-run/{e(r["run_id"])}">Part {r["position"]+1}</a></td><td>{e(", ".join(map(str,r["pages"])))}</td><td>{e(r["state"])}<br>{e(r["error"])}<br>attempts {r["attempts"]}</td><td>{r["proposal_count"]}</td></tr>'
        body+='</tbody></table></div><p>A running call may finish after cancellation. Its result is discarded before another call starts.</p>'
        return page('Selected-page AI batch',body,actor)

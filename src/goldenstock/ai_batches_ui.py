"""Server-rendered preview and progress for selected-page AI batches."""
from fastapi import Request,Query,HTTPException
from fastapi.responses import RedirectResponse
from goldenstock.ai_batches import preview,detail,section_catalog
from goldenstock.inference import PROFILES
from goldenstock.context_ui import context_cards


def mount_batch_ui(app):
    from goldenstock.ui import page,e,form,hidden,actor_or_none

    @app.get('/ai-sections')
    def choose_section(request:Request,job_id:str,q:str=Query('',max_length=120)):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=section_catalog(request,job_id)
        found=[s for s in data['sections'] if q.casefold() in s['title'].casefold()]
        body=f'<h1>Choose a report section</h1><p>{e(data["filename"])} · {data["total_pages"]} original pages</p>'
        body+='<div class="notice">Titles come from extracted financial headings. Page boundaries are inferred from the next detected heading and require review. A page may contain more than one section. Unrecognised headings may be absent.</div>'
        body+='<form method="get">'+hidden('job_id',job_id)+f'<label>Find title<input name="q" value="{e(q)}" maxlength="120"></label><button>Find sections</button></form>'
        body+=f'<p>{len(found)} matching headings. <a href="/ai/{e(data["company_id"])}">Select original pages manually</a></p>'
        if found:
            options=''.join(f'<option value="{e(s["id"])}">{e(s["title"])} · pages {s["page_start"]}–{s["page_end"]} · {e(s["heading"]["method"])}</option>' for s in found)
            profiles=''.join(f'<option value="{e(k)}">{e(p.model)}</option>' for k,p in PROFILES.items())
            body+='<form method="get" action="/ai-batch-preview">'+hidden('job_id',job_id)+hidden('with_context','true')+f'<label>Section<select name="section_id" aria-label="Section">{options}</select></label><label>Local AI profile<select name="profile">{profiles}</select></label><button>Preview section</button></form>'
            body+='<p>The complete inferred range must fit 25 pages and 10 requests. For a larger section, choose a smaller page range manually.</p>'
        else:
            body+='<p>No supported financial headings matched. You can still select original pages manually.</p>'
        return page('Choose a report section',body,actor)

    @app.get('/ai-batch-preview')
    def batch_preview(request:Request,job_id:str,page_start:int=Query(1,ge=1,le=1000),
                      page_end:int=Query(1,ge=1,le=1000),profile:str='qwen4',section_id:str|None=None,with_context:bool=False):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        try:
            data=preview(request,job_id,page_start,page_end,profile,section_id,with_context)
        except HTTPException as exc:
            if exc.status_code!=422: raise
            body='<h1>Choose a smaller range</h1><p>'+e(exc.detail)+f'</p><p><a href="/ai-sections?job_id={e(job_id)}">Choose another section</a> · <a href="/extraction/{e(job_id)}">Select an original page</a></p>'
            response=page('Choose a smaller range',body,actor);response.status_code=422;return response
        page_start,page_end=data['page_start'],data['page_end']
        body=f'<h1>Preview page batch</h1><p>{e(data["filename"])} · original pages {page_start}–{page_end} of {data["total_pages"]}</p><p>{len(data["windows"])} AI requests · {e(data["spec"]["model"])}</p>'
        body+='<div class="notice">All suggestions require review. Primary evidence covers the selected pages. Added nearby context, when enabled, is shown separately with source links.</div>'
        if data.get('section'):
            s=data['section']
            body+=f'<h2>{e(s["title"])}</h2><p>Inferred page range: check the original before starting. '+('Other headings share this page. ' if s['same_page_headings'] else '')+f'<a href="/ai-sections?job_id={e(job_id)}">Choose another section</a></p>'
            heading=s['heading']
            body+=context_cards(dict(context=[heading]),job_id)
        if data['empty_pages']:
            body+='<p>No extracted text on pages: '+e(', '.join(map(str,data['empty_pages'])))+'. These gaps are retained.</p>'
        body+=f'<p><a href="/ai/{e(data["company_id"])}">Change page range or profile</a></p>'
        if data['windows']:
            fields=''.join(hidden(k,v) for k,v in dict(job_id=job_id,page_start=page_start,page_end=page_end,profile=profile,plan_hash=data['plan_hash'],with_context=str(with_context).lower()).items())
            if section_id: fields+=hidden('section_id',section_id)
            body+=form('/api/v1/ai/batches','Start selected-page batch',fields).replace('<form ','<form data-ai-batch="true" ',1)
        for index,window in enumerate(data['windows'],1):
            body+=f'<details class="card"><summary>Request {index} · pages '+e(', '.join(map(str,sorted({x['location']['page'] for x in window['evidence']}))))+'</summary>'
            for entry in window['evidence']:
                start,end=entry['source_range']
                body+=f'<p>Page {entry["location"]["page"]} · characters {start+1}–{end} of {entry["source_length"]}</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{e(entry["text"])}</pre><a href="/normalize/{e(job_id)}/{entry["item_index"]}">Open full source item</a>'
            body+=context_cards(window,job_id)+'</details>'
        return page('Preview page batch',body,actor)

    @app.get('/ai-batch/{key}')
    def batch_result(key:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=detail(key,request); m=data['manifest']
        body=f'<h1>Selected-page AI batch</h1><p>{e(m["filename"])} · original pages {m["page_start"]}–{m["page_end"]}</p><p id="batch-progress">{data["completed"]} / {data["total"]} parts finished · {e(data["state"])}</p>'
        body+='<p>Finished parts may contain errors or no suggestions. Results remain unreviewed. Reload for progress.</p>'
        if m.get('section'): body+=f'<p>Section: {e(m["section"]["title"])} · inferred page range</p>'
        if m.get('with_context'): body+='<p>Nearby context and its separate source links are saved inside each part.</p>'
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

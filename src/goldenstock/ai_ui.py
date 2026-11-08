"""Python pages for private server-side AI jobs."""
import json
from fastapi import Request,Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.models import Job,DocumentVersion,Document,Extraction,AIRun
from goldenstock.ai_runs import runs,run,PROFILES,proposal_evidence
from goldenstock.context_ui import context_cards


def mount_ai_ui(app):
    from goldenstock.ui import page,e,form,hidden,actor_or_none

    def profiles():
        return '<label>Local AI profile<select name="profile">'+''.join(f'<option value="{e(k)}">{e(p.model)}</option>' for k,p in PROFILES.items())+'</select></label>'

    def source_cards(selected,collapsed=False):
        body='<h2>Source fragment</h2><p>The primary evidence and any separately listed context below are sent to local AI. Check headings and year columns in the original. Missing context requires manual review.</p>'
        for item in selected['evidence']:
            index=item.get('item_index',int(item['id'].rsplit(':',1)[1]))
            span=item.get('source_range')
            range_text=f' · characters {span[0]+1}–{span[1]} of {item["source_length"]}' if span else ''
            body+=f'<article class="card"><p>{e(json.dumps(item["location"]))}{e(range_text)}</p><pre class="ai-source" style="white-space:pre-wrap;overflow-wrap:anywhere">{e(item["text"])}</pre><a href="/normalize/{e(selected["job_id"])}/{index}">Open full source item</a></article>'
        body+=context_cards(selected,selected['job_id'])
        if collapsed:
            body='<details><summary>Saved source fragment</summary>'+body+'</details>'
        cursor=selected.get('next_cursor')
        if selected.get('batch_id'):
            body+=f'<p><a href="/ai-batch/{e(selected["batch_id"])}">Back to selected-page batch</a></p>'
        elif cursor:
            body+=f'<p><a href="/ai-evidence?job_id={e(selected["job_id"])}&amp;offset={cursor["offset"]}&amp;text_offset={cursor["text_offset"]}">Preview next fragment</a></p>'
        elif selected.get('selection_version'):
            body+='<p>End of extracted text.</p>'
        return body

    @app.get('/ai-evidence')
    def preview(request:Request,job_id:str,offset:int=Query(0,ge=0,le=49999),
                text_offset:int=Query(0,ge=0,le=16777216)):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        selected=proposal_evidence(request,job_id,offset,text_offset)
        body='<h1>Preview AI evidence</h1><p>Each request covers one bounded fragment. Other fragments run only when you submit them. Suggestions remain unreviewed.</p>'
        body+=f'<p><a href="/extraction/{e(job_id)}?offset={offset}">Back to extracted evidence</a> · <a href="/ai/{e(selected["company_id"])}">AI workspace</a></p>'
        if selected['evidence']:
            fields=hidden('job_id',job_id)+hidden('offset',offset)+hidden('text_offset',text_offset)+profiles()
            body+=form('/api/v1/ai/proposals','Suggest metrics from this fragment',fields).replace('<form ','<form data-ai-proposal="true" ',1)
        else:
            body+='<p>No text in this window. Continue to the next fragment.</p>'
        return page('Preview AI evidence',body+source_cards(selected),actor)

    @app.get('/ai/{company_id}')
    def workspace(company_id:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        body='<h1>AI workspace</h1><div class="notice">Local AI output requires review. Models can misread instructions in documents. No automated valuation or investment recommendation.</div><h2>Suggest metrics</h2><p>Preview a source fragment before sending it. Long text continues in the next fragment. You can also open AI evidence from any extracted item.</p>'
        with Session(request.app.state.engine) as db:
            jobs=list(db.execute(select(Job,DocumentVersion).join(DocumentVersion,Job.version_id==DocumentVersion.id).join(Document,Document.id==DocumentVersion.document_id).join(Extraction,Extraction.version_id==DocumentVersion.id).where(Document.org_id==actor.org_id,Document.owner_id==actor.id,Document.company_id==company_id).order_by(DocumentVersion.created.desc()).limit(50)))
        fields='<label>Extracted original<select name="job_id" required>'+''.join(f'<option value="{e(j.id)}">{e(v.filename)} · v{v.number}</option>' for j,v in jobs)+'</select></label><label>Evidence offset<input type="number" name="offset" min="0" max="49999" value="0" required></label>'
        body+='<form method="get" action="/ai-evidence">'+fields+'<button>Preview evidence</button></form>'
        body+='<h2>Selected PDF pages</h2><p>Preview up to 25 original pages and 10 AI requests. The batch runs through the same local queue.</p>'
        pdfs=''.join(f'<option value="{e(j.id)}">{e(v.filename)} · v{v.number}</option>' for j,v in jobs if v.filename.lower().endswith('.pdf'))
        body+='<form method="get" action="/ai-sections"><label>Report for section selection<select name="job_id" required>'+pdfs+'</select></label><button>Choose section by title</button></form>'
        body+='<form method="get" action="/ai-batch-preview"><label>PDF original<select name="job_id" required>'+pdfs+'</select></label><label>First original page<input name="page_start" type="number" min="1" max="1000" value="1" required></label><label>Last original page<input name="page_end" type="number" min="1" max="1000" value="1" required></label><label>Nearby context<select name="with_context" aria-label="Nearby context"><option value="true">Add automatically with source links</option><option value="false">Selected pages only</option></select></label>'+profiles()+'<button>Preview page batch</button></form>'
        from goldenstock.ai_batches import listing
        batches=listing(request,company_id)
        if batches:
            body+='<h2>Recent page batches</h2>'+''.join(f'<p><a href="/ai-batch/{e(b["id"])}">Open page batch {e(b["id"][:8])}</a></p>' for b in batches)
        body+='<h2>Company summary</h2><p>Uses your confirmed private facts. Missing data remains a gap.</p>'
        body+=form('/api/v1/ai/summaries','Create summary',hidden('company_id',company_id)+profiles())
        body+='<h2>Public SEC research</h2><p>For JPMorgan, HSBC and Nu: fetch supported public XBRL metrics, then create an unreviewed summary. A deployment contact email is required. This covers selected recent metrics, not all reports or periods.</p>'
        body+=form('/api/v1/ai/public-summaries','Research SEC and summarize',hidden('company_id',company_id)+profiles())
        body+=f'<p><a href="/review/{e(company_id)}">Review facts</a> · <a href="/api/v1/knowledge/{e(company_id)}/export">Export private knowledge pack</a></p><h2>Recent tasks</h2><p>Reload for progress. Cancel discards the result; a running GPU call may finish before resources are released.</p>'
        for r in runs(request,company_id):
            body+=f'<p><a href="/ai-run/{e(r["id"])}">{e(r["kind"])} · {e(r["profile"])}</a> · {e(r["state"])} · {e(r["error"])}</p>'
        return page('AI workspace',body,actor)

    @app.get('/ai-run/{run_id}')
    def result(run_id:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=run(run_id,request);output=data['result']
        body=f'<h1>AI task</h1><p>{e(data["kind"])} · {e(data["state"])} · attempts {data["attempts"]}</p><p>{e(data["error"])}</p><a href="/ai/{e(data["company_id"])}">Back to AI workspace</a>'
        from goldenstock.ai_resources_ui import device_choice,execution_cards
        if data['kind']!='batch_proposals':
            if data['state']=='awaiting_device': body+=device_choice(f'/api/v1/ai/runs/{run_id}')
            if data['state'] in {'queued','running','awaiting_device'}: body+=form(f'/api/v1/ai/runs/{run_id}/cancel','Cancel task')
            if data['state'] in {'failed','cancelled'}: body+=form(f'/api/v1/ai/runs/{run_id}/retry','Retry task')
        elif data.get('source_window',{}).get('batch_id'):
            body+=f'<p><a href="/ai-batch/{e(data["source_window"]["batch_id"])}">Batch progress and device choice</a></p>'
        body+=execution_cards(data['executions'])
        if data.get('source_window'):
            body+=source_cards(data['source_window'],collapsed=True)
        if data['state']=='succeeded':
            body+=f'<div class="notice">Unreviewed output · {e(output.get("model"))} · {e(output.get("seconds"))} seconds. Verify against the original.</div>'
            with Session(request.app.state.engine) as db: payload=json.loads(db.get(AIRun,run_id).input)
            for p in output.get('proposals',[]):
                index=int(p['evidence_id'].rsplit(':',1)[1])
                body+=f'<article class="card"><h2>{e(p["metric"])}: {e(p["number_text"])}</h2><p>{e(p["quote"])}</p><p>{e(json.dumps({k:v for k,v in p.items() if k not in {"quote","metric","number_text","evidence_id"}}))}</p><a href="/normalize/{e(payload["job_id"])}/{index}">Check context and create a fact</a></article>'
                cited=[c for c in payload.get('context',[]) if c['id'] in p.get('context_ids',[])]
                if cited: body+=context_cards(dict(context=cited),payload['job_id'])
                if 'context' in payload:
                    missing=[k for k in ('currency','scale','period') if p.get(k) is None]
                    if missing: body+='<p class="notice">Still missing: '+e(', '.join(missing))+'. Check the source context before creating a fact.</p>'
            if data['kind'] in {'summary','public_summary'}:
                body+=f'<p>Latest input period: {e(data["as_of"])}</p>'
                if data['kind']=='summary': body+=f'<p>{"Current inputs" if data["current"] else "Stale — inputs changed"} · {data["blocker_count"]} conflicts</p>'
                else: body+=f'<p>Public data snapshot, not analyst-confirmed inputs. Mixed periods and definitions require review. No claim of current full coverage. <a href="/api/v1/public-snapshots/{e(data["snapshot_id"])}/download">Download original JSON</a></p>'
                for c in output.get('claims',[]):
                    link=f'/api/v1/public-snapshots/{data["snapshot_id"]}' if data['kind']=='public_summary' else f'/facts/{data["company_id"]}#fact-{c["evidence_id"]}'
                    body+=f'<article class="card"><p>Selected source evidence</p><blockquote>{e(c["quote"])}</blockquote><a href="{e(link)}">Source fact</a></article>'
                body+='<h2>Gaps</h2>'+''.join(f'<p>{e(g)}</p>' for g in output.get('gaps',[]))
            body+=f'<details><summary>Versions and provenance</summary><pre style="white-space:pre-wrap">{e(json.dumps({k:v for k,v in output.items() if k not in {"proposals","claims","evidence"}},indent=2))}</pre></details>'
        return page('AI task',body,actor)

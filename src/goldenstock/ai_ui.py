"""Python pages for private server-side AI jobs."""
import json
from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.models import Job,DocumentVersion,Document,Extraction,AIRun
from goldenstock.ai_runs import runs,run,PROFILES


def mount_ai_ui(app):
    from goldenstock.ui import page,e,form,hidden,actor_or_none

    def profiles():
        return '<label>Local AI profile<select name="profile">'+''.join(f'<option value="{e(k)}">{e(p.model)}</option>' for k,p in PROFILES.items())+'</select></label>'

    @app.get('/ai/{company_id}')
    def workspace(company_id:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        body='<h1>AI workspace</h1><div class="notice">Local AI output requires review. Models can misread instructions in documents. No automated valuation or investment recommendation.</div><h2>Suggest metrics</h2><p>Up to 8 extracted items within the context limit per task. Change the offset to continue.</p>'
        with Session(request.app.state.engine) as db:
            jobs=list(db.execute(select(Job,DocumentVersion).join(DocumentVersion,Job.version_id==DocumentVersion.id).join(Document,Document.id==DocumentVersion.document_id).join(Extraction,Extraction.version_id==DocumentVersion.id).where(Document.org_id==actor.org_id,Document.owner_id==actor.id,Document.company_id==company_id).order_by(DocumentVersion.created.desc()).limit(50)))
        fields='<label>Extracted original<select name="job_id" required>'+''.join(f'<option value="{e(j.id)}">{e(v.filename)} · v{v.number}</option>' for j,v in jobs)+'</select></label><label>Evidence offset<input type="number" name="offset" min="0" max="49999" value="0" required></label>'+profiles()
        body+=form('/api/v1/ai/proposals','Suggest metrics',fields)
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
        if data['state'] in {'queued','running'}: body+=form(f'/api/v1/ai/runs/{run_id}/cancel','Cancel task')
        if data['state'] in {'failed','cancelled'}: body+=form(f'/api/v1/ai/runs/{run_id}/retry','Retry task')
        if data['state']=='succeeded':
            body+=f'<div class="notice">Unreviewed output · {e(output.get("model"))} · {e(output.get("seconds"))} seconds. Verify against the original.</div>'
            with Session(request.app.state.engine) as db: payload=json.loads(db.get(AIRun,run_id).input)
            for p in output.get('proposals',[]):
                index=int(p['evidence_id'].rsplit(':',1)[1])
                body+=f'<article class="card"><h2>{e(p["metric"])}: {e(p["number_text"])}</h2><p>{e(p["quote"])}</p><p>{e(json.dumps({k:v for k,v in p.items() if k not in {"quote","metric","number_text","evidence_id"}}))}</p><a href="/normalize/{e(payload["job_id"])}/{index}">Check context and create a fact</a></article>'
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

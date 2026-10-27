"""Human review pairs each current fact with its original extracted evidence."""
import json
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from goldenstock.models import Extraction
from goldenstock.reviews import review_state, snapshots
from goldenstock.normalization import METRICS


def mount_review_ui(app):
    from goldenstock.ui import e, page, form, hidden, actor_or_none

    @app.get('/review/{company_id}')
    def review_page(company_id: str,request: Request,offset: int=0):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        if offset<0: raise HTTPException(422,'Invalid offset')
        current=review_state(request,company_id)
        body='<h1>Analyst review</h1><p>Check source, units, period, scope and warnings. Record a reason for each decision. A corrected fact needs a new review.</p>'
        body+=f'<div class="notice">{current["blocker_count"]} blocking conflicts · {current["unreviewed_count"]} unreviewed inputs · {current["included_count"]} included facts. Rejected facts remain in history.</div>'
        for conflict in current['conflicts'][:30]:
            body+=f'<p>{e(conflict["severity"])}: {e(conflict["kind"].replace("_"," "))} · <a href="/facts/{e(company_id)}#fact-{e(conflict["left"])}">First fact</a> / <a href="/facts/{e(company_id)}#fact-{e(conflict["right"])}">Second fact</a></p>'
        cache={}
        with Session(request.app.state.engine) as db:
            for f in current['facts'][offset:offset+25]:
                if f['version_id'] not in cache:
                    cache[f['version_id']]=json.loads(db.get(Extraction,f['version_id']).payload)
                item=cache[f['version_id']]['items'][f['item_index']]
                original=f'/api/v1/documents/{f["document_id"]}/versions/{f["version_id"]}/download'
                body+=f'<article class="card" id="review-{e(f["id"])}"><h2>{e(METRICS[f["metric"]][0])}: {e(f["value"])} {e(f["currency"] or f["canonical_unit"])}</h2><div class="grid"><section><h3>Source</h3><p style="white-space:pre-wrap">{e((item["text"] or "[empty]")[:5000])}</p><p>{e(json.dumps(item["location"]))}</p><a href="{e(original)}">Download original</a> · <a href="/extraction/{e(f["job_id"])}?offset={f["item_index"]}">Full extracted evidence</a></section><section><h3>Mapped fact</h3><p>{e(f["number_text"])} · {e(f["scale"])} · {e(f["unit"])}<br>{e(f["period_kind"])} {e(f["period_start"])} – {e(f["period_end"])}<br>{e(f["scope"])}: {e(f["scope_detail"])} · {e(f["accounting"])}</p><p>{e(f["definition"])}</p><p>Warnings: {e(", ".join(f["warnings"]) or "None reported")}</p></section></div>'
                decision=f['review']; revision=decision['revision'] if decision else 0
                body+=f'<p>Status: {e(f["review_status"])}</p>'
                if decision: body+=f'<p>Latest decision: {e(decision["note"])}</p>'
                fields=hidden('expected_revision',revision)+'<label>Decision<select name="decision" aria-label="Decision" required><option value="">Choose</option><option value="accepted">Confirm source and context</option><option value="rejected">Reject and exclude</option><option value="unreviewed">Reopen review</option></select></label><label>Reason / checked warnings<input name="note" required minlength="3" maxlength="2000"></label>'
                body+=form('/api/v1/facts/'+f['id']+'/reviews','Record decision',fields)
                body+=f'<p><a href="/normalize/{e(f["job_id"])}/{f["item_index"]}?supersedes={e(f["id"])}">Create corrected version</a> · <a href="/api/v1/facts/{e(f["id"])}/reviews">Decision history</a></p></article>'
        if offset: body+=f'<a href="/review/{e(company_id)}?offset={max(0,offset-25)}">Previous</a> '
        if offset+25<len(current['facts']): body+=f'<a href="/review/{e(company_id)}?offset={offset+25}">Next</a>'
        body+='<h2>Verified input sets</h2><p>Saving requires every included fact to be confirmed and no profit/equity blockers. This is an input set, not an approved valuation. Later changes mark the saved set as stale.</p>'
        fields=hidden('company_id',company_id)+hidden('expected_state_hash',current['state_hash'])+'<label>Input set title<input name="title" required maxlength="160"></label>'
        body+=form('/api/v1/input-snapshots','Save verified input set',fields)
        for saved in snapshots(request,company_id):
            body+=f'<p><a href="/api/v1/input-snapshots/{e(saved["id"])}">{e(saved["title"])}</a> · {"Current" if saved["current"] else "Stale — review changes"}</p>'
        return page('Analyst review',body,actor)

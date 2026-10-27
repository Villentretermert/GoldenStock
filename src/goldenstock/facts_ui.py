"""Explicit evidence mapping now; approval and review workflow belongs to GS-012."""
from fastapi import Request
from fastapi.responses import RedirectResponse
from goldenstock.normalization import METRICS


def mount_facts_ui(app):
    from goldenstock.ui import page, e, form, hidden, actor_or_none
    from goldenstock.documents import extraction_result
    from goldenstock.facts import facts, conflict_queue

    def select(name,label,choices):
        options='<option value="">Choose explicitly</option>'
        options+=''.join(f'<option value="{e(value)}">{e(title)}</option>' for value,title in choices)
        return f'<label>{e(label)}<select name="{e(name)}" aria-label="{e(label)}" required>{options}</select></label>'

    def field(name,label,value='',required=True,kind='text'):
        return f'<label>{e(label)}<input name="{e(name)}" type="{kind}" value="{e(value)}" {"required" if required else ""}></label>'

    @app.get('/normalize/{job_id}/{item_index}')
    def mapping(job_id: str,item_index: int,request: Request,supersedes: str=''):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        from fastapi import HTTPException
        from sqlalchemy.orm import Session
        from goldenstock.models import Document
        result=extraction_result(job_id,request,item_index,1)
        if not result['items']: raise HTTPException(404,'Evidence item not found')
        item=result['items'][0]; raw=item['text'] or ''
        with Session(request.app.state.engine) as db:
            company_id=db.get(Document,result['document_id']).company_id
        fields=hidden('job_id',job_id)+hidden('item_index',item_index)+hidden('supersedes',supersedes)
        fields+=field('number_text','Exact number from this evidence',raw if len(raw)<=80 else '')
        fields+=select('metric','Metric',[(k,v[0]) for k,v in METRICS.items()])
        fields+=select('unit','Reported unit',[(k,k) for k in ['money','count','fraction','percent','bps']])
        fields+=select('scale','Reported scale',[(k,k) for k in ['units','thousands','millions','billions']])
        fields+='<label>Source rounding<select name="rounding"><option value="exact">Exact / rounding not confirmed</option><option value="nearest_reported_digit">Source confirms rounding to nearest displayed digit</option></select></label>'
        fields+=field('currency','Currency code (blank for ratios/counts)',required=False)
        fields+=select('period_kind','Period kind',[(k,k) for k in ['instant','quarter','ytd','year','custom']])
        fields+=field('period_start','Period start (blank for instant)',required=False,kind='date')
        fields+=field('period_end','Period end',kind='date')
        fields+=select('scope','Reporting perimeter',[(k,k) for k in ['group','holding','bank','segment','unknown']])
        fields+=field('scope_detail','Exact entities / segment included')
        fields+=select('accounting','Accounting basis',[(k,k) for k in ['IFRS','US_GAAP','local_GAAP','management','unknown']])
        fields+=field('definition','Metric definition: numerator, denominator, cohort / annualisation')
        fields+=select('disclosure','Disclosure version',[(k,k) for k in ['original','restated','unknown']])
        fields+=field('published_on','Publication date (optional)',required=False,kind='date')
        body='<h1>Normalize evidence</h1><div class="notice">Map a reported number to a metric. Context is supplied by you, not inferred. This creates an unreviewed fact; approval comes later.</div>'
        body+=f'<div class="card"><h2>Original evidence</h2><p style="white-space:pre-wrap">{e(raw)}</p><a href="/extraction/{e(job_id)}?offset={item_index}">Back to evidence</a></div>'
        body+='<details><summary>Metric definitions</summary>'+''.join(f'<p><b>{e(v[0])}:</b> {e(v[3])}</p>' for v in METRICS.values())+'</details>'
        return page('Normalize evidence',body+'<div class="card">'+form('/api/v1/facts','Save unreviewed fact',fields,next='/facts/'+company_id)+'</div>',actor)

    @app.get('/facts/{company_id}')
    def fact_page(company_id: str,request: Request,history: bool=False):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        entries=facts(request,company_id,history); queue=conflict_queue(request,company_id)
        body='<h1>Facts & conflicts</h1><p><a href="/review/'+e(company_id)+'">Open analyst review</a></p><div class="notice">Private facts with recorded review status. No model is approved here. Comparison uses explicitly confirmed source rounding; legacy facts remain exact. Currency conversion is disabled.</div>'
        body+=f'<p>{queue["blocker_count"]} blocking discrepancies · {queue["total"]} comparisons needing attention</p><p><a href="/facts/{e(company_id)}?history=true">Show version history</a> · <a href="/facts/{e(company_id)}">Active facts</a></p>'
        body+='<p>Missing metrics: '+e(', '.join(queue['missing_metrics']))+'</p>'
        for conflict in queue['items'][:30]:
            body+=f'<div class="notice"><b>{e(conflict["severity"].title())}</b> · {e(conflict["kind"].replace("_"," "))} · {e(", ".join(conflict["differences"]))}<br><a href="#fact-{e(conflict["left"])}">First fact</a> / <a href="#fact-{e(conflict["right"])}">Second fact</a></div>'
        if queue['total']>30: body+='<p>Showing the first 30 comparisons; the blocker count covers all comparisons.</p>'
        for f in entries:
            body+=f'<article class="card" id="fact-{e(f["id"])}"><h2>{e(METRICS[f["metric"]][0])}: {e(f["value"])} {e(f["currency"] or f["canonical_unit"])}</h2><p>{"Active" if f["active"] else "Superseded"} · {e(f["review_status"])}</p><p>{e(f["period_kind"])} {e(f["period_start"])} – {e(f["period_end"])}<br>{e(f["scope"])}: {e(f["scope_detail"])} · {e(f["accounting"])}</p><p>{e(f["definition"])}</p><p>Reported: {e(f["number_text"])} · {e(f["scale"])} · {e(f["unit"])}<br>Warnings: {e(", ".join(f["warnings"]) or "None reported")}</p><a href="/extraction/{e(f["job_id"])}?offset={f["item_index"]}">Source evidence</a> · <a href="/normalize/{e(f["job_id"])}/{f["item_index"]}?supersedes={e(f["id"])}">Create corrected version</a></article>'
        body+=f'<p><a href="/ai/{e(company_id)}">AI workspace: suggestions and summary</a></p>'
        return page('Facts & conflicts',body,actor)

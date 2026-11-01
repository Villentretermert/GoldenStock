"""Reporting feed: public provenance, private read state and explicit coverage gaps."""
from datetime import datetime,timezone
from fastapi import Request
from fastapi.responses import RedirectResponse
from goldenstock.monitoring import status,notifications

LABELS={'new_filing':'New disclosure','amended_filing':'Amended disclosure',
    'filing_metadata_changed':'Disclosure metadata changed','nonreliance_disclosure':'Non-reliance disclosure — review required',
    'possible_revision':'Previously reported number changed — review required','new_metric_period':'New reported metric / period',
    'source_error':'Source check failed','source_recovered':'Source available again'}


def mount_monitoring_ui(app):
    from goldenstock.ui import page,e,form,actor_or_none

    def stamp(value):
        return datetime.fromtimestamp(value,timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if value is not None else 'Not checked yet'

    @app.get('/updates')
    def updates(request:Request,offset:int=0,unread:bool=False):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        feed=notifications(request,offset,unread);coverage=status(request)
        body=f'<h1>Reporting updates</h1><p>{feed["unread_count"]} unread · Notifications for companies in your watchlist, delivered only on this site.</p>'
        if not coverage['scheduler_ready']: body+='<div class="notice">Monitoring scheduler is not responding. New checks are delayed; saved updates remain available. Start or check the monitor container.</div>'
        body+='<p><a href="/updates">All updates</a> · <a href="/updates?unread=true">Unread only</a> · <a href="#coverage">Coverage and check status</a></p>'
        body+='<div class="notice">New public disclosures require analyst review. Existing facts, calculations and valuations stay unchanged. Changes in XBRL values or amended filings are signals to investigate, not a confirmed accounting restatement.</div>'
        if not feed['items']: body+='<article class="card"><h2>No updates in this view</h2><p>The first successful check records a baseline without sending historical filings. Later changes appear here. Follow companies below and check the source status.</p></article>'
        for item in feed['items']:
            d=item['detail'];after=d.get('after');before=d.get('before')
            body+=f'<article class="card" id="notification-{e(item["id"])}"><span class="tag">{"Read" if item["read_at"] else "Unread"} · {e(item["company_id"].upper())}</span><h2 style="margin-top:12px">{e(LABELS[item["kind"]])}</h2><p>{e(stamp(item["created"]))} · SEC {e(item["source_kind"])}</p>'
            if after:
                if item['source_kind']=='facts':
                    body+=f'<p><strong>{e(after["namespace"])}:{e(after["tag"])}</strong> · {e(after["unit"])}</p><p>Period: {e(after["start"] or "instant")} — {e(after["end"])}</p>'
                    body+=f'<p>Previously: {e(before["value"] if before else "Not observed")} → Now: <strong>{e(after["value"])}</strong></p>'
                else: body+=f'<p><strong>{e(after["form"])}</strong> · filed {e(after["filed"])} · report period {e(after["report_date"] or "not specified")}</p>'
                body+=f'<p><a href="{e(after["url"])}" target="_blank" rel="noopener noreferrer">Official SEC filing</a> · Accession {e(after["accession"])}</p>'
                if after['form'].startswith('6-K'): body+='<p>6-K can contain other issuer information; confirm that this disclosure contains financial reporting.</p>'
                for label,key in [('Previous source JSON','before_snapshot_id'),('Current source JSON','after_snapshot_id')]:
                    if d.get(key): body+=f'<p><a href="/api/v1/monitor-snapshots/{e(d[key])}/download">{label}</a></p>'
                body+=f'<p><a href="/review/{e(item["company_id"])}">Review company facts</a> · <a href="/files?company_id={e(item["company_id"])}">Upload new English report</a> · <a href="/templates">Choose a template for a new calculation</a></p>'
            elif item['kind']=='source_error': body+=f'<p>Check failed: {e(d["error"])}. Last successful source data is retained. Automatic retries use backoff; see status below.</p>'
            else: body+='<p>The source has returned a valid response. Check the latest changes and coverage below.</p>'
            if not item['read_at']: body+=form(f'/api/v1/notifications/{item["id"]}/read','Mark as read')
            body+='</article>'
        if offset>0: body+=f'<a href="/updates?offset={max(0,offset-50)}&unread={str(unread).lower()}">Previous</a> '
        if feed['has_more']: body+=f'<a href="/updates?offset={offset+50}&unread={str(unread).lower()}">Next</a>'
        body+='<h2 id="coverage">Coverage and check status</h2><p>Checks run about every six hours while this computer and worker are running. One shared check serves all followers. Manual requests have a 15-minute cooldown.</p><div class="grid">'
        for c in coverage['companies']:
            body+=f'<article class="card"><h3>{e(c["name"])}</h3><p>{"Following via watchlist" if c["following"] else "Not in your watchlist"}</p>'
            if not c['following']: body+=form('/api/v1/favorites/'+c['company_id'],'Follow reporting',method='PUT')
            else: body+=form('/api/v1/favorites/'+c['company_id'],'Remove from watchlist',method='DELETE')
            if c['coverage']=='english_connector_gap': body+='<p>Coverage gap: no verified English monitoring connector. <a href="/sources">View official source registry</a>.</p>'
            else:
                body+='<p>SEC recent filings and selected standard XBRL profit/equity/assets tags. This is not complete report coverage.</p>'
                if c['can_check']: body+=form('/api/v1/monitoring/'+c['company_id']+'/check','Request check')
                for s in c['sources']:
                    body+=f'<p><strong>{e(s["kind"])}</strong><br>Last attempt: {e(stamp(s["last_attempt"]))}<br>Last success: {e(stamp(s["last_success"]))}<br>Next due: {e(stamp(s["next_check"])) if s["next_check"] else "When followed / next worker cycle"}<br>Known items: {s["known_items"]} · {e(s["error"] or ("Baseline recorded" if s["last_success"] else "Waiting for baseline"))}</p>'
                    if s['snapshot_id']: body+=f'<p><a href="/api/v1/monitor-snapshots/{e(s["snapshot_id"])}/download">Latest source JSON</a></p>'
            body+='</article>'
        body+='</div>'
        return page('Reporting updates',body,actor)

"""Reporting feed: public provenance, private read state and explicit coverage gaps."""
from datetime import datetime,timezone
from fastapi import Request
from fastapi.responses import RedirectResponse
from goldenstock.monitoring import status,notifications
from goldenstock.monitor_history import values,history

LABELS={'new_filing':'New disclosure','amended_filing':'Amended disclosure',
    'filing_metadata_changed':'Disclosure metadata changed','nonreliance_disclosure':'Non-reliance disclosure — review required',
    'possible_revision':'Previously reported number changed — review required','new_metric_period':'New reported metric / period',
    'source_error':'Source check failed','source_recovered':'Source available again'}


def mount_monitoring_ui(app):
    from goldenstock.ui import page,e,form,actor_or_none

    def stamp(value):
        return datetime.fromtimestamp(value,timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if value is not None else 'Not checked yet'

    def source_card(title,value,snapshot_id):
        if not value: return '<section><h3>'+title+'</h3><p>Not previously observed for this exact metric, unit and period.</p></section>'
        body='<section><h3>'+title+'</h3><p style="font-size:1.4em;overflow-wrap:anywhere"><strong>'+e(value['value'])+'</strong> '+e(value['unit'])+'</p>'
        body+='<p>Period: '+e(value['start'] or 'Instant')+' — '+e(value['end'])+'</p>'
        body+='<p>Filed '+e(value['filed'])+' · '+e(value['form'])+'</p>'
        body+='<p>'+e(value.get('definition') or 'Taxonomy description was not included in this saved observation.')+'</p>'
        body+='<p><a href="'+e(value['url'])+'" target="_blank" rel="noopener noreferrer">Official SEC filing</a><br>Accession '+e(value['accession'])+'</p>'
        if snapshot_id: body+='<p><a href="/api/v1/monitor-snapshots/'+e(snapshot_id)+'/download">Source JSON</a></p>'
        body+='<details><summary>Source location</summary><p style="overflow-wrap:anywhere">'+e(value.get('json_path','Unavailable'))+'</p></details></section>'
        return body

    def comparison_note(result,unit):
        if not result['comparable']:
            return '<p>'+('New metric or period; no previous comparable value.' if result['reason']=='new_metric_period' else 'Context or definition differs; no automatic numeric comparison.')+'</p>'
        body='<p><strong>Change: '+e(result['delta'])+' '+e(unit)+'</strong>'
        body+=' · '+e(result['percent'])+'%' if result['percent'] is not None else ' · Percentage unavailable: previous value is zero'
        if result['significant']: body+=' <span class="tag">Change of at least 5%</span>'
        return body+'</p>'

    @app.get('/updates')
    def updates(request:Request,offset:int=0,unread:bool=False,category:str='all'):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        feed=notifications(request,offset,unread,category);coverage=status(request)
        body=f'<h1>Reporting updates</h1><p>{feed["unread_count"]} unread · Notifications for companies in your watchlist, delivered only on this site.</p>'
        if not coverage['scheduler_ready']: body+='<div class="notice">Monitoring scheduler is not responding. New checks are delayed; saved updates remain available. Start or check the monitor container.</div>'
        body+='<p><a href="/updates">All updates</a> · <a href="/updates?unread=true">Unread only</a> · <a href="#coverage">Coverage and check status</a></p>'
        body+='<p><a href="/updates?category=revisions">Revisions to observed periods</a> · <a href="/updates?category=periods">New metrics and periods</a> · <a href="/updates?category=other">Other disclosures and source status</a></p><p>Value changes appear first. Highlighting starts at 5%, calculated against the absolute previous value. Smaller changes remain visible.</p>'
        body+='<div class="notice">New public disclosures require analyst review. Existing facts, calculations and valuations stay unchanged. Changes in XBRL values or amended filings are signals to investigate, not a confirmed accounting restatement.</div>'
        if not feed['items']: body+='<article class="card"><h2>No updates in this view</h2><p>The first successful check records a baseline without sending historical filings. Later changes appear here. Follow companies below and check the source status.</p></article>'
        last_group=None
        for item in feed['items']:
            group='Revisions to observed periods' if item['kind']=='possible_revision' else 'New metrics and periods' if item['kind']=='new_metric_period' else 'Other disclosures and source status'
            if group!=last_group: body+='<h2>'+group+'</h2>';last_group=group
            d=item['detail'];after=d.get('after');before=d.get('before')
            body+=f'<article class="card" id="notification-{e(item["id"])}"><span class="tag">{"Read" if item["read_at"] else "Unread"} · {e(item["company_id"].upper())}</span><h2 style="margin-top:12px">{e(LABELS[item["kind"]])}</h2><p>{e(stamp(item["created"]))} · SEC {e(item["source_kind"])}</p>'
            if after:
                if item['source_kind']=='facts':
                    body+=f'<p><strong>{e(after["namespace"])}:{e(after["tag"])}</strong> · {e(after["unit"])}</p><p>Period: {e(after["start"] or "instant")} — {e(after["end"])}</p>'
                    body+=comparison_note(item['comparison'],after['unit'])
                    body+='<p>Scope: entire filing entity reported by SEC companyfacts. Confirm the issuer’s reporting perimeter before using this in a model.</p>'
                    body+='<div class="grid">'+source_card('Previous publication',before,d.get('before_snapshot_id'))+source_card('New publication',after,d.get('after_snapshot_id'))+'</div>'
                    body+=f'<p><a href="/monitoring/{e(item["source_id"])}/history/{e(item["item_key"])}">Observed value history</a></p>'
                else: body+=f'<p><strong>{e(after["form"])}</strong> · filed {e(after["filed"])} · report period {e(after["report_date"] or "not specified")}</p>'
                if item['source_kind']!='facts': body+=f'<p><a href="{e(after["url"])}" target="_blank" rel="noopener noreferrer">Official SEC filing</a> · Accession {e(after["accession"])}</p>'
                if after['form'].startswith('6-K'): body+='<p>6-K can contain other issuer information; confirm that this disclosure contains financial reporting.</p>'
                for label,key in ([] if item['source_kind']=='facts' else [('Previous source JSON','before_snapshot_id'),('Current source JSON','after_snapshot_id')]):
                    if d.get(key): body+=f'<p><a href="/api/v1/monitor-snapshots/{e(d[key])}/download">{label}</a></p>'
                body+=f'<p><a href="/review/{e(item["company_id"])}">Review company facts</a> · <a href="/files?company_id={e(item["company_id"])}">Upload new English report</a> · <a href="/templates">Choose a template for a new calculation</a></p>'
            elif item['kind']=='source_error': body+=f'<p>Check failed: {e(d["error"])}. Last successful source data is retained. Automatic retries use backoff; see status below.</p>'
            else: body+='<p>The source has returned a valid response. Check the latest changes and coverage below.</p>'
            if not item['read_at']: body+=form(f'/api/v1/notifications/{item["id"]}/read','Mark as read')
            body+='</article>'
        if offset>0: body+=f'<a href="/updates?offset={max(0,offset-50)}&unread={str(unread).lower()}&category={e(category)}">Previous</a> '
        if feed['has_more']: body+=f'<a href="/updates?offset={offset+50}&unread={str(unread).lower()}&category={e(category)}">Next</a>'
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
                    if s['kind']=='facts': body+=f'<p><a href="/monitoring/{e(s["id"])}">Observed values and history</a></p>'
            body+='</article>'
        body+='</div>'
        return page('Reporting updates',body,actor)

    @app.get('/monitoring/{source_id}')
    def observed_values(source_id:str,request:Request,offset:int=0):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=values(source_id,request,offset)
        body='<h1>Observed SEC values</h1><p><a href="/updates">Reporting updates</a></p><p>Selected standard profit, equity and assets tags. Missing observations remain gaps; they are not zero. History includes source refreshes that do not send notifications.</p>'
        for item in data['items']:
            value=item['value']
            body+='<article class="card"><h2>'+e(value.get('label') or value['tag'])+'</h2><p>'+e(value['namespace']+':'+value['tag'])+'</p><p>'+e(value['value']+' '+value['unit'])+' · '+e(value['start'] or 'Instant')+' — '+e(value['end'])+'</p>'
            body+=f'<a href="/monitoring/{e(source_id)}/history/{e(item["item_key"])}">Observed value history</a></article>'
        if not data['items']: body+='<p>No values observed yet.</p>'
        if offset: body+=f'<a href="/monitoring/{e(source_id)}?offset={max(0,offset-50)}">Previous</a> '
        if data['has_more']: body+=f'<a href="/monitoring/{e(source_id)}?offset={offset+50}">Next</a>'
        return page('Observed SEC values',body,actor)

    @app.get('/monitoring/{source_id}/history/{item_key}')
    def observed_history(source_id:str,item_key:str,request:Request,offset:int=0):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=history(source_id,item_key,request,offset)
        body='<h1>Observed value history</h1><p><a href="/updates">Reporting updates</a> · <a href="/monitoring/'+e(source_id)+'">Observed SEC values</a></p>'
        body+='<p>'+e(data['scope'])+'. Newest observation first. An unchanged number in a new source does not send another notification.</p>'
        titles={'legacy_baseline':'Retained value at history upgrade','baseline':'First observed baseline','possible_revision':'Value changed — analyst review required','new_metric_period':'First observation of this metric / period','source_refresh':'Source refreshed; numeric value unchanged'}
        for row in data['items']:
            body+='<article class="card"><h2>'+e(titles[row['reason']])+'</h2><p>Observed '+e(stamp(row['created']))+' · version '+str(row['revision'])+'</p>'
            body+='<p>'+e(row['value']['namespace']+':'+row['value']['tag'])+'</p>'+source_card('Published value',row['value'],row['snapshot_id'])+'</article>'
        if not data['items']: body+='<p>No history recorded yet.</p>'
        prefix=f'/monitoring/{e(source_id)}/history/{e(item_key)}?offset='
        if offset: body+='<a href="'+prefix+str(max(0,offset-20))+'">Previous</a> '
        if data['has_more']: body+='<a href="'+prefix+str(offset+20)+'">Next</a>'
        return page('Observed value history',body,actor)

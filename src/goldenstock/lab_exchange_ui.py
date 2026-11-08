"""Python pages for workbook annotation and explicit import confirmation."""
import json
from fastapi import Request
from fastapi.responses import RedirectResponse
from goldenstock.lab_exchange import drafts,draft_detail,import_detail
from goldenstock.normalization import METRICS


def mount_exchange_ui(app):
    from goldenstock.ui import page,e,form,hidden,actor_or_none

    def upload():
        fields='<label>Completed annotation workbook<input type="file" name="file" accept=".xlsx" required></label>'
        return form('/api/v1/lab/exchange/imports','Preview workbook import',fields).replace('<form ','<form data-upload="true" data-lab-import="true" ',1)

    def label_cards(values,evidence,empty):
        if not values: return '<p>'+empty+'</p>'
        sources={item['id']:item for item in evidence};body=''
        for value in values:
            if isinstance(value,str):
                body+='<blockquote>'+e(sources[value]['text'])+'</blockquote>'
                continue
            name=METRICS[value['metric']][0]
            body+='<article class="card"><h3>'+e(name)+': '+e(value['number_text'])+'</h3>'
            body+='<p>'+e(' · '.join(value.get(k) or 'Not stated' for k in ('currency','scale','period')))+'</p>'
            body+='<p>Reporting perimeter: '+e(value.get('perimeter') or 'Not stated')+'<br>Definition: '+e(value.get('definition') or 'Not stated')+'</p>'
            body+='<blockquote>'+e(value['quote'])+'</blockquote></article>'
        return body

    @app.get('/lab/workbooks')
    def index(request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        body='<h1>Annotation workbooks</h1><p><a href="/lab/new">Choose evidence for a new workbook</a> · <a href="/lab">AI Lab</a></p>'
        body+='<p>Private XLSX exchange, up to four cases and twelve labels per case. Download a draft, complete its labels and case review statuses, then preview the import. Saving requires your confirmation.</p>'+upload()
        for item in drafts(request): body+=f'<p><a href="/lab/workbooks/{e(item["id"])}">{e(item["title"])}</a></p>'
        return page('Annotation workbooks',body,actor)

    @app.get('/lab/workbooks/{key}')
    def workbook(key:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=draft_detail(key,request)
        body=f'<h1>{e(data["title"])}</h1><p>Annotation workbook · {e(data["kind"])} · {e(data["split"])}</p><p><a href="/lab/workbooks">All annotation workbooks</a></p>'
        body+=f'<p><a class="button" href="/api/v1/lab/exchange/drafts/{e(key)}/download">Download annotation XLSX</a></p>'
        body+='<ol><li>Fill blue cells on Labels. Preserve numbers as text and quote the original.</li><li>On Cases, choose labelled or explicitly no_relevant_facts for every case.</li><li>Upload the workbook and check the before/after preview before confirming.</li></ol>'
        body+='<p>Sources and version fields must remain unchanged. Formulas and external links are rejected. Maximum file size: 1 MiB.</p>'+upload()
        if data['parent_id']: body+=f'<p>Base reference: <a href="/lab/datasets/{e(data["parent_id"])}">version {data["parent_revision"]}</a>. Saving creates a new immutable version when labels change.</p>'
        else: body+='<p>This is an unlabelled draft. It is not an accepted reference or a negative example.</p>'
        for i,case in enumerate(data['cases'],1):
            body+=f'<h2>Case C{i}: {e(case["company_id"])}</h2>'
            for source in case['evidence']:
                body+='<details><summary>'+e(source['id'])+'</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+e(source['text'])+'</pre><p>'+e(json.dumps(source['location']))+'</p></details>'
            if case['source'].get('job_id'): body+=f'<p><a href="/extraction/{e(case["source"]["job_id"])}">Open extracted original</a></p>'
        if data['imports']:
            body+='<h2>Import history</h2>'
            for item in data['imports']: body+=f'<p><a href="/lab/workbook-imports/{e(item["id"])}">{"Saved reference" if item["dataset_id"] else "Pending confirmation"} {e(item["id"][:8])}</a></p>'
        return page('Annotation workbook',body,actor)

    @app.get('/lab/workbook-imports/{key}')
    def review_import(key:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=import_detail(key,request)
        body=f'<h1>Review workbook changes</h1><p>{e(data["title"])} · {e(data["kind"])} · {e(data["split"])}</p><p><a href="/lab/workbooks/{e(data["exchange_id"])}">Source workbook</a> · <a href="/api/v1/lab/exchange/imports/{e(key)}/original">Download submitted original</a></p>'
        if data['conflict']: body+='<div class="notice">'+e(data['conflict'])+'</div>'
        for change in data['changes']:
            body+=f'<h2>Case {e(change["case"])}: {len(change["before"])} previous / {len(change["after"])} imported labels</h2>'
            body+='<div class="grid"><section><h3>Previous labels</h3>'+label_cards(change['before'],change['evidence'],'No saved labels.')+'</section>'
            body+='<section><h3>Imported labels</h3>'+label_cards(change['after'],change['evidence'],'Explicitly marked: no relevant facts.')+'</section></div>'
            body+='<details><summary>Frozen source evidence</summary>'
            for evidence in change['evidence']: body+='<blockquote>'+e(evidence['text'])+'</blockquote><p>'+e(evidence['id']+' '+json.dumps(evidence['location']))+'</p>'
            body+='</details>'
        if data['dataset_id']:
            body+=f'<p>Saved with your confirmation: {e(data["confirmation_note"])}</p><a class="button" href="/lab/datasets/{e(data["dataset_id"])}">Open saved reference</a>'
        elif not data['conflict']:
            fields=hidden('candidate_hash',data['candidate_hash'])+'<label>Review note<textarea name="reason" minlength="5" maxlength="1000" required></textarea></label>'
            fields+='<label><input class="check" type="checkbox" name="reference_confirmed" value="true" required> I checked every included label and every no_relevant_facts decision against the original.</label>'
            body+='<p>This saves an AI Lab reference. It does not approve financial facts, a valuation or the pilot.</p>'
            body+=form('/api/v1/lab/exchange/imports/'+key+'/confirm','Confirm and save reference',fields).replace('<form ','<form data-lab-confirm="true" ',1)
        return page('Review workbook changes',body,actor)

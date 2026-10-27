"""Server-rendered template library and explicit structure sharing."""
from fastapi import Request
from fastapi.responses import RedirectResponse
from goldenstock.templates import listing,detail


def mount_templates_ui(app):
    from goldenstock.ui import page,e,form,hidden,actor_or_none

    def upload_fields(template_id=''):
        return hidden('template_id',template_id)+'<label>Template title<input name="title" required maxlength="160"></label><label>XLSX template<input type="file" name="file" accept=".xlsx" required></label>'

    @app.get('/templates')
    def library(request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        body='<h1>Excel templates</h1><p>Versioned structures for future calculations. Uploads are private by default.</p><p><a href="/api/v1/templates/demo">Download synthetic demo XLSX</a></p><div class="notice">Contract v1: Model and GS_Map sheets, up to 100 mapped cells. Arithmetic only; no Excel functions, macros, external links or circular references. Upload limit 50 MB, expanded package limit 5 MB. Validation does not calculate a valuation.</div>'
        body+=form('/api/v1/templates','Validate and save template',upload_fields(),upload=True)
        for row in listing(request):
            body+=f'<article class="card"><a href="/templates/{e(row["id"])}">{e(row["title"])}</a><p>{"Shared structure" if row["shared"] else "Private"}</p></article>'
        return page('Excel templates',body,actor)

    @app.get('/templates/{template_id}')
    def show(template_id:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=detail(template_id,request);owner=data['owner_id']==actor.id
        body=f'<h1>{e(data["title"])}</h1><p>{"Shared structure" if data["shared"] else "Private template"}</p>'
        body+='<div class="notice">Sharing exposes the title, field keys, units, periods, definitions and formulas to your fund. The structure has blank inputs, no original comments, other text, cached results or document properties. Only the author can download the original. Review mapping text before sharing.</div>'
        if owner:
            body+=form('/api/v1/templates/'+template_id+'/visibility','Make private' if data['shared'] else 'Share clean structure with fund',hidden('shared',str(not data['shared']).lower())+hidden('revision',data['revision']),method='PATCH')
            body+='<h2>New version</h2><p>Saving a version makes this template private again.</p>'+form('/api/v1/templates','Validate new version',upload_fields(template_id),upload=True)
        body+=form('/api/v1/templates/'+template_id+'/copy','Create private structure copy',next='/templates')
        for v in data['versions']:
            link=f'/api/v1/templates/{template_id}/versions/{v["id"]}'
            body+=f'<article class="card"><h2>Version {v["number"]}</h2><p>Compatible with {e(v["contract"]["policy"])}. Not calculated.</p><a href="{link}/structure">Download clean structure</a>'
            if owner: body+=f' · <a href="{link}/original">Download private original</a>'
            body+='<div class="table-wrap"><table class="template-map"><tr><th>Key</th><th>Role</th><th>Cell</th><th>Unit / period</th><th>Definition</th></tr>'
            for f in v['contract']['fields']:
                body+=f'<tr><td>{e(f["key"])}</td><td>{e(f["role"])}</td><td>{e(f["cell"])}</td><td>{e(f["unit"])} / {e(f["period"])}</td><td>{e(f["definition"])}</td></tr>'
            body+='</table></div></article>'
        return page('Template versions',body,actor)

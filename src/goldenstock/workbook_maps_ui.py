"""Python-rendered workbook wizard: source, mapping, review, immutable template."""
from urllib.parse import urlencode
from fastapi import Request
from fastapi.responses import RedirectResponse
from goldenstock.workbook_maps import listing,detail
from goldenstock.workbook_mapping import BANK_METRICS,FACTORS


def mount_workbook_maps_ui(app):
    from goldenstock.ui import page,e,form,hidden,actor_or_none

    def upload_form(title='',parent=''):
        fields=hidden('parent_id',parent)+f'<label>Workbook title<input name="title" required maxlength="160" value="{e(title)}"></label><label>Private XLSX workbook<input type="file" name="file" accept=".xlsx" required></label>'
        return form('/api/v1/workbook-maps','Inspect workbook',fields,upload=True).replace('<form ','<form data-map-upload="true" ',1)

    def select(name,label,options,current):
        return f'<label>{e(label)}<select name="{e(name)}">'+''.join(f'<option value="{e(k)}" {"selected" if k==current else ""}>{e(v)}</option>' for k,v in options)+'</select></label>'

    @app.get('/workbook-maps')
    def library(request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        body='<h1>Map an Excel workbook</h1><p>1. Inspect your workbook → 2. Map cells → 3. Confirm changes → 4. Calculate.</p><div class="notice">Private originals and maps stay with you. Up to 20 sheets, 20,000 populated cells, 40 mappings and 20 MB expanded. No VBA, external connections or iterative calculations. Unsupported formulas require a manual decision or exclusion.</div>'
        body+='<section class="card">'+upload_form()+'</section>'
        for row in listing(request):
            body+=f'<article class="card"><a href="/workbook-maps/{e(row["id"])}">{e(row["title"])}</a><p>{"Finalized" if row["version_id"] else "Draft"} · Revision {row["revision"]}</p></article>'
        return page('Workbook mapping',body,actor)

    @app.get('/workbook-maps/{ident}')
    def show(ident:str,request:Request,sheet:str='',cell:str='',key:str='',offset:int=0):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=detail(ident,request);result=data['preview'];frozen=bool(data['version_id']);base='/api/v1/workbook-maps/'+ident
        body=f'<h1>{e(data["title"])}</h1><p>Workbook mapping · {"Finalized" if frozen else "Private draft"} · Revision {data["revision"]}</p><p><a href="/workbook-maps">All workbooks</a> · <a href="{base}/original">Download private original</a></p>'
        body+='<div class="notice">Confirming a map approves cell meanings and conversion rules. It does not approve reported facts or a valuation. Source numbers are shown for inspection only; calculation inputs require a separate confirmation.</div>'
        if frozen:
            body+=f'<p><a class="button" href="/templates/{e(data["template_id"])}">Open generated template</a> <a class="button" href="/calculations/new?template_id={e(data["template_id"])}&version_id={e(data["version_id"])}&workbook_map={e(ident)}">Review workbook inputs and calculate</a></p>'
            body+='<details class="card"><summary>Upload a new workbook version</summary><p>Unchanged mappings retain approval. Changed labels, formats, formulas or dependencies require confirmation again. Numeric changes require input review at calculation.</p>'+upload_form(data['title'],ident)+'</details>'
        body+='<section class="card"><h2>Mapping review</h2>'
        for error in result['errors']: body+='<p role="alert">'+e(error)+'</p>'
        if not frozen:
            body+=f'<form data-map-confirm="true" data-api="{base}/confirm">'+hidden('revision',data['revision'])+hidden('preview_hash',result['hash'] or '')
        body+='<p>Scroll horizontally on a narrow screen to see all columns.</p><div class="table-wrap"><table class="template-map workbook-map"><tr><th>Confirm</th><th>Metric / source</th><th>Reported → normalized</th><th>Meaning / change</th></tr>'
        for row in result['rows']:
            m=row['mapping'];url='/workbook-maps/'+ident+'?'+urlencode(dict(key=m['key'],sheet=m['sheet'],cell=m['cell']))+'#edit'
            check='Confirmed' if row['confirmed'] else (f'<input class="check" type="checkbox" name="keys" value="{e(m["key"])}" aria-label="Confirm {e(m["key"])}">' if not frozen and not row['error'] else 'Needs repair')
            body+=f'<tr><td>{check}</td><td><a href="{e(url)}">{e(m["key"])}</a><br>{e(m["sheet"])}!{e(m["cell"])}</td><td>{e(row["source"]["value"])} → {e(row["normalized"] or "formula / manual input")}<br>{e(m["scale"])} → {e(m["unit"])}</td><td>{e(m["period"])} · {e(m["definition"])}<br>{e(row["change"])} · {e(m["mode"])}<br>{e(row["error"] or m["decision"])}</td></tr>'
        body+='</table></div>'
        if not frozen:
            body+='<label><input class="check" type="checkbox" name="confirmed" required> I checked the selected cells, units, scale, period, definitions and formula decisions.</label><button>Confirm selected mappings</button></form>'
        if result['removed']: body+='<p>Removed from previous map: '+e(', '.join(result['removed']))+'</p>'
        body+='</section>'
        if result.get('sample'):
            sample=result['sample']['scenarios']['base']
            body+='<details class="card"><summary>Calculation preview — unverified workbook numbers</summary><p>'+e(sample['state'])+'</p>'
            if sample['error']: body+='<p>'+e(sample['error'])+'</p>'
            for k,v in sample['values'].items(): body+='<p>'+e(k)+': '+e(v['value'])+'</p>'
            body+='</details>'
        body+='<details class="card"><summary>Excluded formulas ('+str(len(result['omitted_formulas']))+')</summary><p>These cells are not part of the generated calculation. First 100 shown; download the private original for the complete workbook.</p>'
        for item in result['omitted_formulas'][:100]: body+='<p>'+e(item['sheet']+'!'+item['cell']+' '+item['formula'])+'</p>'
        body+='</details>'
        if not frozen and result['contract'] and not result['errors'] and all(r['confirmed'] for r in result['rows']):
            body+=f'<section class="card"><h2>Save immutable template</h2><form data-map-finalize="true" data-api="{base}/finalize">'+hidden('revision',data['revision'])+hidden('preview_hash',result['hash'])+'<label><input class="check" type="checkbox" name="acknowledge_omitted" required> I accept the complete map, manual decisions, removed mappings and exclusion of all unselected cells/formulas.</label><button>Finalize private template</button></form></section>'
        sheets=data['inspection']['sheets'];visible=[s for s in sheets if sheets[s]['visible']]
        selected=next((x['mapping'] for x in data['entries'] if x['mapping']['key']==key),{})
        sheet=sheet if sheet in visible else (visible[0] if visible else '')
        if not frozen and visible:
            current=dict(key='',sheet=sheet,cell=cell,mode='input',unit='USD',scale='units',period='assumption',definition='',decision='')|selected
            body+='<section class="card" id="edit"><h2>Add or edit a mapping</h2><p>Choose one of the nine bank metric codes, or enter a custom identifier. Definitions must specify profit/equity scope and ratio methodology. Percent-formatted Excel cells usually store a fraction: inspect the raw number below before choosing scale.</p>'
            body+=f'<form data-map-edit="true" data-api="{base}/mapping" data-method="PUT">'+hidden('revision',data['revision'])
            body+=f'<label>Metric key<input name="key" list="bank-metrics" required pattern="[a-z][a-z0-9_]{{0,39}}" maxlength="40" value="{e(current["key"])}"></label><datalist id="bank-metrics">'+''.join(f'<option value="{k}">{e(v[0])}</option>' for k,v in BANK_METRICS.items())+'</datalist><div class="grid">'
            body+=select('sheet','Source sheet',[(s,s) for s in visible],current['sheet'])+f'<label>Source cell<input name="cell" required value="{e(current["cell"])}" pattern="[A-Z]{{1,3}}[1-9][0-9]{{0,6}}"></label>'
            body+=select('mode','Cell treatment',[('input','Numeric input'),('formula','Translate arithmetic formula'),('manual','Replace with manual input (reason required)')],current['mode'])
            body+=select('unit','Normalized unit',[(v,v) for v in ['USD','EUR','GBP','RUB','ratio','multiple','count','years']],current['unit'])
            body+=select('scale','Raw number scale',[(k,k+' × '+v) for k,v in FACTORS.items()],current['scale'])
            body+=f'<label>Period (FYyyyy or assumption)<input name="period" required value="{e(current["period"])}"></label></div><label>Definition / perimeter<input name="definition" required minlength="3" maxlength="160" value="{e(current["definition"])}"></label><label>Manual decision reason<input name="decision" maxlength="500" value="{e(current["decision"])}"></label><button>Save mapping and preview</button></form>'
            if selected: body+=form(base+'/mapping','Remove mapping',hidden('revision',data['revision'])+hidden('key',selected['key']),method='DELETE')
            body+='</section>'
        body+='<section class="card"><h2>Source cells</h2><form method="get">'+select('sheet','Worksheet',[(s,s) for s in visible],sheet)+'<button>Show worksheet</button></form><p>Raw values and formulas; no cached Excel result is treated as verified.</p><div class="table-wrap"><table><tr><th>Cell</th><th>Raw value / formula</th><th>Format</th></tr>'
        cells=sorted(sheets.get(sheet,{}).get('cells',{}).items(),key=lambda x:(x[1]['row'],x[1]['column']));offset=max(0,min(offset,len(cells)))
        for address,value in cells[offset:offset+100]:
            url='/workbook-maps/'+ident+'?'+urlencode(dict(sheet=sheet,cell=address))+'#edit'
            body+=f'<tr><td><a href="{e(url)}">{e(address)}</a></td><td>{e(value["value"])}</td><td>{e(value["format"])}</td></tr>'
        body+='</table></div><p>'
        for start,label in [(offset-100,'Previous cells'),(offset+100,'Next cells')]:
            if 0<=start<len(cells): body+=f'<a href="{e("/workbook-maps/"+ident+"?"+urlencode(dict(sheet=sheet,offset=start)))}">{label}</a> · '
        body+='</p></section>'
        return page('Workbook mapping',body,actor)

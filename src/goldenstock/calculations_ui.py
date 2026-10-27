"""Python-rendered scenario entry, source provenance and saved calculations."""
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from goldenstock.calculations import listing, detail, fact_matches
from goldenstock.templates import detail as template_detail
from goldenstock.companies import companies
from goldenstock.reviews import snapshots, snapshot as input_snapshot


def mount_calculations_ui(app):
    from goldenstock.ui import page,e,hidden,form,actor_or_none

    @app.get('/calculations')
    def library(request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        body='<h1>Calculations</h1><p>Private, saved scenarios. Choose a version in <a href="/templates">Templates</a> to start.</p>'
        for row in listing(request):
            body+=f'<article class="card"><h2><a href="/calculations/{e(row["id"])}">{e(row["title"])}</a></h2><p>{e(row["company_id"])} · {e(row["state"].replace("_"," "))}</p></article>'
        return page('Calculations',body,actor)

    @app.get('/calculations/new')
    def new(request:Request,template_id:str,version_id:str,company_id:str='jpm',snapshot_id:str=''):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        template=template_detail(template_id,request)
        version=next((v for v in template['versions'] if v['id']==version_id),None)
        if not version: raise HTTPException(404,'Template version not found')
        issuers=companies(request)
        if company_id not in {c['id'] for c in issuers}: raise HTTPException(404,'Company not found')
        sets=[s for s in snapshots(request,company_id) if s['current']]
        if snapshot_id not in {s['id'] for s in sets}: snapshot_id=''
        evidence=input_snapshot(snapshot_id,request)['snapshot']['facts'] if snapshot_id else []
        fields=version['contract']['fields'];inputs=[f for f in fields if f['role']=='input']
        body=f'<h1>Calculate scenarios</h1><p>{e(template["title"])} · Version {version["number"]}</p>'
        body+='<div class="notice">All inputs are explicit. Original workbook values are never imported automatically. Manual inputs are assumptions, even when they describe a historical year. A completed calculation is not an approved valuation.</div>'
        body+='<form method="get">'+hidden('template_id',template_id)+hidden('version_id',version_id)+'<label>Company<select name="company_id">'
        body+=''.join(f'<option value="{e(c["id"])}" {"selected" if c["id"]==company_id else ""}>{e(c["name"])}</option>' for c in issuers)
        body+='</select></label><label>Verified input set<select name="snapshot_id"><option value="">Manual assumptions only</option>'
        for snap in sets:
            body+=f'<option value="{e(snap["id"])}" {"selected" if snap["id"]==snapshot_id else ""}>{e(snap["title"])}</option>'
        body+='</select></label><button>Load company and input set</button></form><p>When changing company, load it first to see its input sets.</p><hr>'
        body+='<form data-calculation="true" data-api="/api/v1/calculations">'+hidden('template_id',template_id)+hidden('version_id',version_id)+hidden('company_id',company_id)+hidden('snapshot_id',snapshot_id)
        body+='<label>Calculation title<input name="title" required maxlength="160"></label>'
        body+='<p><a href="/review/'+e(company_id)+'">Review facts and input sets</a>. Choose a compatible verified fact or enter a manual number. Confirm that its definition and perimeter match the field. Ratios use fractions: 0.05 means 5%. Money uses currency units, without a thousands/millions scale.</p>'
        for scenario in ('base','optimistic','stress'):
            body+=f'<section class="card"><h2>{scenario.title()}</h2>'
            if scenario!='base': body+=f'<label><input class="check" type="checkbox" name="enable.{scenario}"> Include this scenario</label>'
            for f in inputs:
                prefix=f'{scenario}.{f["key"]}'
                body+=f'<fieldset><legend>{e(f["key"])} · {e(f["unit"])} / {e(f["period"])}</legend><p>{e(f["definition"])}</p><div class="grid">'
                body+=f'<label>Manual value<input name="{e(prefix)}.value" inputmode="decimal" maxlength="80" placeholder="Decimal number"></label>'
                body+=f'<label>Or verified fact<select name="{e(prefix)}.fact_id"><option value="">Use manual value</option>'
                for fact in evidence:
                    if fact_matches(f,fact):
                        label=f'{fact["definition"]} | {fact["value"]} {fact["currency"] or fact["canonical_unit"]} | {fact["period_end"]} | {fact["scope_detail"]}'
                        body+=f'<option value="{e(fact["id"])}">{e(label)}</option>'
                body+='</select></label></div>'
                body+=f'<label>Reason / definition and perimeter check<input name="{e(prefix)}.note" maxlength="1000"></label></fieldset>'
            body+='</section>'
        body+='<section class="card"><h2>Control checks</h2><p>Optional: compare a calculated field with an expected value. For a balance, map its residual as a formula and check it against zero. Tolerance uses the field’s unit, without display rounding.</p>'
        for n in range(3):
            body+=f'<fieldset><legend>Check {n+1}</legend><label>Calculated field<select name="check.{n}.key"><option value="">No check</option>'
            body+=''.join(f'<option value="{e(f["key"])}">{e(f["key"])} · {e(f["unit"])}</option>' for f in fields if f['role']!='input')
            body+=f'</select></label><div class="grid"><label>Expected value<input name="check.{n}.expected" value="0"></label><label>Absolute tolerance<input name="check.{n}.tolerance" value="0"></label></div><label>Reason for check / tolerance<input name="check.{n}.note" maxlength="1000"></label></fieldset>'
        body+='</section><label><input class="check" type="checkbox" name="confirmed" required> I checked every included value, source mapping, definition and assumption.</label><button>Calculate and save private scenarios</button></form>'
        return page('Calculate scenarios',body,actor)

    @app.get('/calculations/{run_id}')
    def show(run_id:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=detail(run_id,request);payload=data['input'];result=data['result'];template=payload['template']
        body=f'<h1>{e(data["title"])}</h1><p>{e(data["company_id"])} · {e(template["title"])} v{template["number"]} · {e(data["engine"])}</p>'
        body+=f'<div class="notice">Status: {e(data["state"].replace("_"," "))}. These are arithmetic results, not an approved investment valuation. '
        if data['inputs_current'] is False: body+='Source review has changed: these historical results require a new calculation. '
        if data['inputs_current'] is None: body+='All inputs are manually confirmed assumptions. '
        if not payload['checks']: body+='No control checks were configured. '
        body+='</div>'+form('/api/v1/calculations/'+run_id+'/replay','Verify reproducibility',next='/calculations/'+run_id+'?replayed=1')
        if request.query_params.get('replayed')=='1': body+='<p role="status">Replay matched the saved result hash.</p>'
        body+='<div class="table-wrap"><table class="template-map"><thead><tr><th>Field / unit / period</th>'
        names=list(result['scenarios']);body+=''.join(f'<th>{e(n.title())}</th>' for n in names)+'</tr></thead><tbody>'
        for f in template['contract']['fields']:
            body+=f'<tr><td>{e(f["key"])}<br><small>{e(f["unit"])} / {e(f["period"])}</small></td>'
            for name in names:
                val=result['scenarios'][name]['values'].get(f['key'])
                body+=f'<td>{e(val["display"]) if val else "Not calculated"}</td>'
            body+='</tr>'
        body+='</tbody></table></div>'
        for name,scenario in result['scenarios'].items():
            body+=f'<section class="card"><h2>{e(name.title())}: {e(scenario["state"].replace("_"," "))}</h2>'
            if scenario['error']: body+=f'<p role="alert">{e(scenario["error"]["key"])}: {e(scenario["error"]["code"])}</p>'
            for check in scenario['checks']:
                body+=f'<p>{e(check["key"])}: {"PASS" if check["passed"] else "BLOCKED"} · residual {e(check["residual"])} · tolerance {e(check["tolerance"])}<br>{e(check["note"])}</p>'
            body+='<details><summary>Inputs, sources and exact values</summary>'
            for key,item in payload['scenarios'][name].items():
                body+=f'<p><strong>{e(key)}</strong>: {e(item["value"])} · {e(item["source"].replace("_"," "))}<br>{e(item["note"])}</p>'
                if item.get('fact'):
                    fact=item['fact'];body+=f'<p>Fact {e(fact["id"])} · {e(fact["definition"])} · {e(fact["scope_detail"])}<br>{e(fact["filename"])} · {e(fact["location"])}</p>'
            body+='<p>Unrounded calculated values: '+e({k:v['value'] for k,v in scenario['values'].items()})+'</p></details></section>'
        body+='<details class="card"><summary>Reproducibility receipt</summary><p>Input SHA-256: '+e(data['input_hash'])+'</p><p>Result SHA-256: '+e(data['result_hash'])+'</p><p>34 significant digits; HALF_EVEN arithmetic; HALF_UP display. Currency: 2 decimals; other units: 6. Display rounding is not used in formulas or checks.</p></details>'
        return page('Saved calculation',body,actor)

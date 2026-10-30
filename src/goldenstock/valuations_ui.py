"""Analyst-led method selection, common-equity reconciliation and sensitivity views."""
from decimal import Decimal
from fastapi import Request,HTTPException
from fastapi.responses import RedirectResponse
from goldenstock.calculations import detail as calculation_detail
from goldenstock.valuations import listing,detail
from goldenstock.valuation_engine import METHODS,input_fields


def mount_valuations_ui(app):
    from goldenstock.ui import page,e,hidden,form,actor_or_none

    @app.get('/valuations')
    def library(request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        body='<h1>Equity valuations</h1><p>Start from a saved <a href="/calculations">calculation</a>. Values and supporting evidence remain private.</p>'
        for row in listing(request):
            body+=f'<article class="card"><h2><a href="/valuations/{e(row["id"])}">{e(row["title"])}</a></h2><p>{e(METHODS[row["method"]])} · {e(row["state"])}</p></article>'
        return page('Equity valuations',body,actor)

    @app.get('/valuations/new')
    def new(request:Request,calculation_id:str,method:str='pe',currency:str='USD',reference_year:int=2025,operating:bool=False):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        source=calculation_detail(calculation_id,request)
        if method not in METHODS or currency not in {'USD','EUR','GBP','RUB'} or not 1900<=reference_year<=2200:
            raise HTTPException(422,'Choose a supported method, currency and reference year')
        if source['state']=='blocked' or source['inputs_current'] is False: raise HTTPException(409,'Use a nonblocked calculation with current source facts')
        body=f'<h1>Value common equity</h1><p>Source: <a href="/calculations/{e(calculation_id)}">{e(source["title"])}</a> · {e(source["company_id"])}</p>'
        body+='<div class="notice">Confirm definitions and the reporting perimeter. The calculator does not decide whether a bank is comparable or whether cash is distributable. DCF v1 values five calendar years from a year-end date. No automatic FX, ADR conversion or trading recommendation.</div>'
        body+='<form method="get">'+hidden('calculation_id',calculation_id)+'<div class="grid"><label>Method<select name="method">'
        body+=''.join(f'<option value="{k}" {"selected" if k==method else ""}>{e(label)}</option>' for k,label in METHODS.items())
        body+='</select></label><label>Currency<select name="currency">'+''.join(f'<option {"selected" if c==currency else ""}>{c}</option>' for c in ('USD','EUR','GBP','RUB'))+'</select></label>'
        body+=f'<label>Reference financial year<input name="reference_year" type="number" min="1900" max="2200" value="{reference_year}"></label></div><label><input class="check" type="checkbox" name="operating" value="true" {"checked" if operating else ""}> Include monthly user economics</label><button>Load method inputs</button></form><hr>'
        body+='<form data-valuation="true" data-api="/api/v1/valuations">'+hidden('calculation_id',calculation_id)+hidden('method',method)+hidden('currency',currency)+hidden('reference_year',reference_year)+hidden('operating',str(operating).lower())
        body+='<label>Valuation title<input name="title" required maxlength="160"></label>'
        body+=f'<label>Valuation date<input name="valuation_date" type="date" value="{reference_year}-12-31" required></label>'
        method_help='Regulatory capital needs, reinvestment, distribution capacity and terminal growth' if method in ('ddm','fcfe') else 'Comparable banks, source/date of the multiple, accounting basis, risk, profitability and period'
        for name,label in [('method_note',method_help),('scope_note','Reporting perimeter and common-equity reconciliation'),('shares_note','Common-share count, dilution and quote instrument basis')]:
            body+=f'<label>{e(label)}<textarea name="{name}" required minlength="20" maxlength="2000" rows="3"></textarea></label>'
        gate='capital_confirmed' if method in ('ddm','fcfe') else 'comparability_confirmed'
        label='I checked cash distributions after capital requirements; the discount rate is cost of equity.' if gate=='capital_confirmed' else 'I checked the comparables, multiple basis and the common-share denominator.'
        body+=f'<label><input class="check" type="checkbox" name="{gate}" required> {e(label)}</label>'
        if method=='pb': body+='<p>Total equity is retained as supplied. Common book equity = total equity − NCI − preferred equity. An absent adjustment requires an explicit zero.</p>'
        if method=='pe': body+='<p>Common earnings = profit attributable to parent shareholders − preferred dividends. Do not use total group profit including NCI.</p>'
        if operating:
            body+='<div class="notice">User economics is separate from company equity value. Constant monthly revenue, margin and retention are assumptions. LTV assumes the first contribution payment at the end of month one and excludes acquisition cost; 100% retention cannot produce a finite lifetime.</div>'
            body+='<label>Operating month<input type="month" name="operating_month" required></label><label>Activity definition, same-month revenue, cohort and constant-retention assumptions<textarea name="operating_note" rows="3" minlength="20" maxlength="2000" required></textarea></label>'
        fields=input_fields(method,currency,reference_year,operating)
        original=source['input']['template']['contract']['fields']
        body+='<p>Each included scenario needs every input. Use currency units and decimal ratios (0.05 = 5%). A source field must match the required unit and period; check its meaning yourself.</p>'
        for scenario in source['result']['scenarios']:
            body+=f'<section class="card"><h2>{e(scenario.title())}</h2>'
            if scenario!='base': body+=f'<label><input class="check" type="checkbox" name="enable.{e(scenario)}"> Include this scenario</label>'
            for f in fields:
                prefix=f'{scenario}.{f["key"]}'
                body+=f'<fieldset><legend>{e(f["key"])} · {e(f["unit"])} / {e(f["period"])}</legend><p>{e(f["definition"])}</p><div class="grid"><label>Manual assumption<input name="{e(prefix)}.value" inputmode="decimal" maxlength="80"></label><label>Or source calculation field<select name="{e(prefix)}.source_key"><option value="">Use manual assumption</option>'
                for candidate in original:
                    if candidate['unit']==f['unit'] and candidate['period']==f['period']:
                        body+=f'<option value="{e(candidate["key"])}">{e(candidate["key"])} — {e(candidate["definition"])}</option>'
                body+=f'</select></label></div><label>Input justification / semantic check<input name="{e(prefix)}.note" maxlength="1000"></label></fieldset>'
            body+='</section>'
        body+='<details class="card"><summary>Optional ordinary-share quote for upside comparison</summary><p>Price must be for one common economic share in the valuation currency. No quote means no upside estimate. GBp and depositary receipts need a separately documented conversion before entry.</p>'
        for name,label,kind in [('quote_price','Price','text'),('quote_date','Quote date','date'),('quote_instrument','Ordinary-share instrument','text'),('quote_source','Quote source and conversion explanation, if applicable','text')]:
            body+=f'<label>{e(label)}<input name="{name}" type="{kind}" maxlength="500"></label>'
        body+='</details><label><input class="check" type="checkbox" name="method_confirmed" required> I checked the method, every included input and all scope assumptions.</label><button>Calculate and save equity valuation</button></form>'
        return page('Value common equity',body,actor)

    @app.get('/valuations/{run_id}')
    def show(run_id:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=detail(run_id,request);payload=data['input'];result=data['result'];currency=payload['currency']
        body=f'<h1>{e(data["title"])}</h1><p>{e(METHODS[data["method"]])} · {currency} · as of {e(payload["valuation_date"])}</p>'
        body+='<div class="notice">'+('<strong>Source review changed. Create a new calculation and valuation.</strong><br>' if data['inputs_current'] is False else '')+'<br>'.join(e(w) for w in payload['warnings'])+'</div>'
        body+='<p><a href="/calculations/'+e(data['calculation_id'])+'">Open source calculation</a> · <a href="/valuations/new?calculation_id='+e(data['calculation_id'])+'">Evaluate another method</a></p>'
        body+=form('/api/v1/valuations/'+run_id+'/replay','Verify valuation reproducibility',next='/valuations/'+run_id+'?replayed=1')
        if result['state'] != 'blocked':
            body+='<section class="card"><h2>Download this valuation</h2><p>All files use this saved version. XLSX is an editable calculation; PDF and PPTX contain the saved results and source appendix.</p><p>'
            body+=' · '.join(f'<a download href="/api/v1/valuations/{e(run_id)}/export/{kind}">Download {kind.upper()}</a>' for kind in ('xlsx','pdf','pptx'))
            body+='</p><p>Source review status is checked at export. Files remain private until you share them.</p></section>'
        if request.query_params.get('replayed')=='1': body+='<p role="status">Valuation replay matched the saved result.</p>'
        body+='<div class="grid" style="margin-top:20px">'
        for name,scenario in result['scenarios'].items():
            body+=f'<article class="card"><h2>{e(name.title())}</h2>'
            if scenario['state']=='blocked': body+='<p role="alert">Blocked: '+e('; '.join(scenario['errors']).replace('_',' '))+'</p>'
            else:
                values=scenario['values'];body+=f'<p class="valuation-price">{e(values["per_share"]["display"])} {currency}</p><p>Per common share<br>Common equity: {e(values["equity_value"]["display"])} {currency}</p>'
                if 'upside' in scenario: body+=f'<p>Upside vs supplied quote: {Decimal(scenario["upside"])*100:.2f}%</p>'
                else: body+='<p>Upside unavailable — no quote supplied.</p>'
                if 'terminal_share' in values: body+=f'<p>Terminal contribution: {Decimal(values["terminal_share"]["value"])*100:.2f}%</p>'
            body+='</article>'
        body+='</div>'
        for name,scenario in result['scenarios'].items():
            if scenario['state']=='blocked': continue
            body+=f'<section class="card"><h2>{e(name.title())}: sensitivity</h2>'
            if data['method'] in ('ddm','fcfe'):
                body+='<p>Cost of equity ±1 percentage point; terminal growth ±0.5 percentage point. Other inputs fixed. Invalid combinations are blocked.</p><div class="table-wrap"><table class="sensitivity"><tr><th>Cost of equity / growth</th>'
                points=scenario['sensitivity']
                body+=''.join(f'<th>{Decimal(p["inputs"]["terminal_growth"])*100:.2f}%</th>' for p in points[:3])+'</tr>'
                for row in (points[:3],points[3:6],points[6:]):
                    body+=f'<tr><th>{Decimal(row[0]["inputs"]["cost_equity"])*100:.2f}%</th>'
                    body+=''.join('<td>'+e(p['per_share']['display'] if p['per_share'] else 'Blocked')+'</td>' for p in row)+'</tr>'
                body+='</table></div>'
            else:
                body+='<p>Selected multiple × 0.8, × 1.0 and × 1.2; earnings/book equity fixed.</p><div class="table-wrap"><table class="sensitivity"><tr><th>Multiple</th><th>Value per share</th></tr>'
                for point in scenario['sensitivity']:
                    body+=f'<tr><td>{e(point["inputs"]["multiple"])}</td><td>{e(point["per_share"]["display"] if point["per_share"] else "Blocked")} {currency}</td></tr>'
                body+='</table></div>'
            body+='<details><summary>Calculated fields and reconciliation</summary><div class="table-wrap"><table class="sensitivity"><tr><th>Meaning</th><th>Value</th></tr>'
            for f in payload['contract']['fields']:
                if f['role']=='output': body+=f'<tr><td>{e(f["definition"])}</td><td>{e(scenario["values"][f["key"]]["display"])} {e(f["unit"])}</td></tr>'
            body+='</table></div></details><details><summary>Input provenance and assumptions</summary>'
            for key,item in payload['scenarios'][name].items():
                body+=f'<p><strong>{e(key)}</strong>: {e(item["value"])} · {e(item["source"])}<br>{e(item["note"])}</p>'
                if item.get('source_key'): body+=f'<p>Source: {e(item["source_key"])} — {e(item["source_definition"])}</p>'
            body+='</details></section>'
        body+='<section class="card"><h2>Method and reporting perimeter</h2>'
        for key in ('method_note','scope_note','shares_note','operating_note'):
            if payload.get(key): body+='<p>'+e(payload[key])+'</p>'
        if payload['operating']: body+='<p>Operating month: '+e(payload['operating_month'])+'. User contribution LTV is separate from company equity.</p>'
        if payload['quote']:
            q=payload['quote'];body+=f'<p>Quote: {e(q["price"])} {e(q["currency"])} · {e(q["date"])} · {e(q["instrument"])}<br>{e(q["source"])}</p>'
        body+='<details><summary>Reproducibility receipt</summary><p>'+e(data['policy'])+' · '+e(payload['engine'])+'</p><p>Input: '+e(data['input_hash'])+'</p><p>Result: '+e(data['result_hash'])+'</p></details></section>'
        return page('Equity valuation',body,actor)

"""Python-rendered pages; browser forms call only the authenticated local API."""
from html import escape
import secrets
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from goldenstock.auth import authenticate
from goldenstock.accounts import list_models, users
from goldenstock.companies import companies, company
from goldenstock.sources import registry


def e(value):
    return escape(str(value), quote=True)


CSS = '''
*{box-sizing:border-box}body{margin:0;background:#f5f5ef;color:#193b30;font:16px/1.55 system-ui,sans-serif}
header{background:white;border-bottom:1px solid #d9e0d6;padding:18px 5%;display:flex;align-items:center;gap:24px;flex-wrap:wrap}
.brand,h1,h2{font-family:Georgia,serif}.brand{font-size:28px;text-decoration:none}nav{display:flex;gap:18px;flex-wrap:wrap}
a{color:#245d47}main{max-width:1120px;padding:30px 24px 70px;margin:auto}h1{font-size:40px;margin:10px 0}h2{font-size:25px;margin-top:0}
.muted{color:#66756c}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,290px),1fr));gap:20px}
.card{background:white;border:1px solid #d8e0d6;border-radius:12px;padding:24px;margin-bottom:20px;min-width:0;overflow-wrap:anywhere}
.tag{font-size:13px;color:#735b22;background:#f5edd6;padding:4px 9px;border-radius:5px}.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
button,.button{background:#285641;color:white;border:0;border-radius:6px;padding:10px 16px;font:inherit;cursor:pointer;text-decoration:none}
button:disabled{opacity:.5;cursor:wait}input,select{max-width:100%;width:100%;padding:10px;border:1px solid #b8c7b9;border-radius:5px;font:inherit;background:white}
label{display:block;margin:10px 0 16px}label input,label select{display:block;margin-top:5px}form{margin:0}form.inline{display:inline-block}
.login{max-width:460px;margin:60px auto}.login h1{font-size:34px}.notice{border-left:3px solid #b58a39;padding:12px 18px;background:#f8f1df;margin:18px 0}
#message{color:#9b2929;white-space:pre-wrap}.table-wrap{overflow-x:auto}td,th{padding:12px;text-align:left;vertical-align:top;border-bottom:1px solid #d8e0d6}td{max-width:600px;overflow-wrap:anywhere}
.template-map{min-width:760px}
@media(max-width:600px){h1{font-size:30px}header{padding:16px 22px;gap:12px}main{padding:22px 16px}.card{padding:18px}nav{gap:12px;font-size:14px}}
'''
JS = '''
document.querySelectorAll('form[data-api]').forEach(form=>form.addEventListener('submit',async event=>{
event.preventDefault();const message=document.getElementById('message');message.textContent='';
const button=form.querySelector('button');if(button)button.disabled=true;
try{const fields=new FormData(form);let body;const headers={'X-CSRF-Token':document.querySelector('meta[name="csrf"]').content};
if(form.dataset.upload){body=fields;form.dataset.requestKey ||= crypto.randomUUID();headers['Idempotency-Key']=form.dataset.requestKey;}
else{let values=Object.fromEntries(fields);for(const k of ['shared','active'])if(k in values)values[k]=values[k]==='true';
if('revision' in values)values.revision=Number(values.revision);body=JSON.stringify(values);headers['Content-Type']='application/json';}
const response=await fetch(form.dataset.api,{method:form.dataset.method||'POST',headers,body});const result=await response.json();
if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Please check the entered values');
location.href=form.dataset.next||location.pathname+location.search;
}catch(error){message.textContent=error.message;message.scrollIntoView({block:'center'});}finally{if(button)button.disabled=false;}
}));
'''


def form(url, button, fields='', method='POST', next='', upload=False):
    return f'<form class="inline" data-api="{e(url)}" data-method="{method}" data-next="{e(next)}" {"data-upload=true" if upload else ""}>{fields}<button>{e(button)}</button></form>'


def hidden(name, value):
    return f'<input type="hidden" name="{e(name)}" value="{e(value)}">'


def page(title, body, actor=None):
    nonce = secrets.token_urlsafe(20)
    nav = '' if not actor else '<nav><a href="/">Watchlist</a><a href="/catalog">Companies</a><a href="/sources">Sources</a><a href="/models">Models</a><a href="/templates">Templates</a><a href="/files">Files & jobs</a>'+('<a href="/team">Team</a>' if actor.account_admin else '')+'</nav><span class="muted">'+e(actor.login)+'</span>'+form('/api/v1/auth/logout','Sign out',next='/login')
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="csrf" content="{e(actor.csrf if actor else '')}"><title>{e(title)} · GoldenStock</title><style>{CSS}</style></head>
    <body><header><a class="brand" href="/">GoldenStock</a>{nav}</header><main><div id="message" role="alert"></div>{body}</main><script nonce="{nonce}">{JS}</script></body></html>'''
    return HTMLResponse(html, headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
        'Referrer-Policy':'same-origin','Content-Security-Policy':f"default-src 'self'; script-src 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})


def actor_or_none(request):
    try:
        return authenticate(request)
    except HTTPException:
        return None


def company_card(c):
    action = form('/api/v1/favorites/'+c['id'],'Remove from watchlist' if c['favorite'] else 'Add to watchlist',method='DELETE' if c['favorite'] else 'PUT')
    return f'''<article class="card"><span class="tag">{'Candidate — awaiting confirmation' if c['candidate'] else 'Pilot company'}</span>
    <h2 style="margin-top:16px"><a href="/company/{e(c['id'])}">{e(c['name'])}</a></h2><p class="muted">{e(c['identifier'])}</p>
    <p>Report data: {e(c['freshness'])}<br>Valuation: not calculated</p>{action}</article>'''


def mount_ui(app):
    from goldenstock.templates_ui import mount_templates_ui
    mount_templates_ui(app)
    from goldenstock.ai_ui import mount_ai_ui
    mount_ai_ui(app)
    from goldenstock.facts_ui import mount_facts_ui
    mount_facts_ui(app)
    from goldenstock.review_ui import mount_review_ui
    mount_review_ui(app)
    @app.get('/extraction/{job_id}', response_class=HTMLResponse)
    def extraction_page(job_id: str, request: Request, offset: int = 0):
        from goldenstock.documents import extraction_result
        import json
        actor=actor_or_none(request)
        if not actor:
            return RedirectResponse('/login',status_code=303)
        result=extraction_result(job_id,request,offset,100)
        body='<h1>Extracted evidence</h1><div class="notice">Unreviewed. Check the original before using these values. OCR confidence measures recognition, not financial accuracy. English language requires analyst confirmation.</div>'
        original=f'/api/v1/documents/{result["document_id"]}/versions/{result["version_id"]}/download'
        body+=f'<p><a href="{e(original)}">{e(result["filename"])}</a> · Version {result["version_number"]} · {result["total"]} items</p><p>Warnings: {e(", ".join(result["warnings"]).replace("_", " ") or "None reported")}</p>'
        body+='<div class="table-wrap"><table><thead><tr><th>Origin</th><th>Raw value</th><th>Method / confidence</th></tr></thead><tbody>'
        for item_index,item in enumerate(result['items'],offset):
            value='[empty]' if item['text'] is None else item['text']
            location=item['location']
            origin=' · '.join(f'{key.title()} {location[key]}' for key in ('page','slide','sheet','table','cell','row','column') if key in location)
            formula=f'<br>Formula: {e(item["formula"])} (cached value unverified)' if item.get('formula') else ''
            body+=f'<tr><td>{e(origin)}</td><td style="white-space:pre-wrap">{e(value)}{formula}</td><td>{e(item["method"])} / {e(item["confidence"] if item["confidence"] is not None else "not scored")}<br><a href="/normalize/{e(job_id)}/{item_index}">Normalize</a></td></tr>'
        body+='</tbody></table></div>'
        if offset:
            body+=f'<a href="/extraction/{e(job_id)}?offset={max(0,offset-100)}">Previous</a> '
        if offset+100<result['total']:
            body+=f'<a href="/extraction/{e(job_id)}?offset={offset+100}">Next</a>'
        return page('Extracted evidence',body,actor)

    @app.get('/sources', response_class=HTMLResponse)
    def sources_page(request: Request, company_id: str = ''):
        actor = actor_or_none(request)
        if not actor:
            return RedirectResponse('/login', status_code=303)
        entries = registry(company_id)
        body = '<h1>Public sources</h1><p>Official issuer and regulatory references. Reviewed 22 October 2026.</p><div class="notice">Target coverage: FY2023–2025 and published 2026 quarters. Coverage is incomplete. No reports ingested; automated collection is disabled. Unverified English material remains a gap, without translation.</div>'
        body += '<p><a href="/sources">All companies</a></p>'
        for item in entries:
            body += f'<article class="card"><h2>{e(item["title"])}</h2><p><a href="/company/{e(item["company_id"])}">Company</a> · {e(item["kind"].replace("_", " "))}</p><p><a rel="noreferrer" href="{e(item["url"])}">Open official reference</a></p><p>Availability: {e(item["availability"].replace("_", " "))}<br>English: {e(item["english"])}<br>Review: {e(item["checked_on"])} · {e(item["review_freshness"])}</p><p>{e(item["evidence"])}</p><p>Usage review: {e(item["terms_status"].replace("_", " "))}. {e(item["terms_note"])}</p>'
            if item['terms_url']:
                body += f'<p><a rel="noreferrer" href="{e(item["terms_url"])}">Source usage policy</a></p>'
            body += '</article>'
        return page('Public sources', body, actor)

    @app.get('/files', response_class=HTMLResponse)
    def files_page(request: Request, company_id: str = '', q: str = ''):
        from goldenstock.documents import documents
        actor = actor_or_none(request)
        if not actor:
            return RedirectResponse('/login',status_code=303)
        choices = ''.join(f'<option value="{e(c["id"])}" {"selected" if c["id"]==company_id else ""}>{e(c["name"])}</option>' for c in companies(request))
        entries = documents(request,q,company_id)
        previous = '<option value="">New document</option>'+''.join(f'<option value="{e(d["id"])}">New version: {e(d["filename"])}</option>' for d in entries)
        fields = '<label>Company<select name="company_id" aria-label="Company">'+choices+'</select></label><label>Document<select name="document_id" aria-label="Document">'+previous+'</select></label><label>Original file<input type="file" name="file" accept=".pdf,.xlsx,.pptx" required></label>'
        body = '<h1>Files & jobs</h1><p class="muted">Private originals, immutable versions and a persistent verification queue.</p><div class="card">'+form('/api/v1/documents','Upload private original',fields,upload=True)+'</div><div class="notice">PDF, XLSX or PPTX, up to 50 MB. Verification checks file integrity, not financial accuracy or malware safety. After verification, extract English text and cells locally. Scanned PDFs use OCR; all results require review.</div><p><a href="'+e(str(request.url.path)+('?'+'company_id='+company_id if company_id else ''))+'">Refresh processing status</a></p>'
        for doc in entries:
            body += '<div class="card"><h2>'+e(doc['filename'])+'</h2>'
            for version in doc['versions']:
                url=f'/api/v1/documents/{doc["id"]}/versions/{version["version_id"]}/download'
                body += f'<p>Version {version["number"]} · {e(version["state"])} · {version["size"]} bytes<br><small>SHA-256: {e(version["sha256"])}</small></p><div class="row"><a href="{url}">Download original</a><a href="/api/v1/jobs/{version["job_id"]}">Job history</a>'
                if version['state']=='failed':
                    body += form('/api/v1/jobs/'+version['job_id']+'/retry','Retry processing')
                if version['state']=='succeeded' and version['kind']=='verify_original':
                    body += form('/api/v1/jobs/'+version['job_id']+'/extract','Extract English document')
                if version['state']=='succeeded' and version['kind']=='extract_document':
                    body += '<a href="/extraction/'+version['job_id']+'">View extracted evidence</a>'
                body += '</div>'
            body += '</div>'
        if not entries:
            body += '<div class="card"><h2>No uploaded files</h2><p>Your colleagues cannot see your private originals.</p></div>'
        return page('Files',body,actor)

    @app.get('/login', response_class=HTMLResponse)
    def login_page():
        fields = '<label>Login<input name="login" autocomplete="username" required maxlength="120"></label><label>Password<input name="password" type="password" autocomplete="current-password" required minlength="12" maxlength="128"></label>'
        return page('Sign in','<div class="card login"><h1>Your research workspace</h1><p class="muted">Sign in to your fund’s private workspace.</p>'+form('/api/v1/auth/login','Sign in',fields,next='/')+'<p class="muted">Ask your account administrator for access.</p></div>')

    @app.get('/', response_class=HTMLResponse)
    @app.get('/catalog', response_class=HTMLResponse)
    def home(request: Request, q: str = ''):
        actor = actor_or_none(request)
        if not actor:
            return RedirectResponse('/login',status_code=303)
        catalog = request.url.path == '/catalog'
        entries = companies(request,q,not catalog)
        body = f'<h1>{"Company catalog" if catalog else "Your watchlist"}</h1><p class="muted">Track companies and keep your evidence in one place.</p>'
        body += '<form method="get" class="row"><input aria-label="Search companies" name="q" placeholder="Search companies" value="'+e(q)+'" style="max-width:400px"><button>Search</button></form><br>'
        body += '<div class="grid">'+''.join(company_card(c) for c in entries)+'</div>'
        if not entries:
            body += '<div class="card"><h2>No companies yet</h2><p>Add a company from the catalog to build your personal watchlist.</p><a class="button" href="/catalog">Browse companies</a></div>'
        return page('Companies',body+'<div class="notice">AI summaries and valuations are not available yet. Missing financial data is shown explicitly.</div>',actor)

    @app.get('/company/{company_id}', response_class=HTMLResponse)
    def details(company_id: str, request: Request):
        actor = actor_or_none(request)
        if not actor:
            return RedirectResponse('/login',status_code=303)
        c = company(company_id,request)
        source = '<a href="/ai/'+e(company_id)+'">AI workspace</a> · <a href="/facts/'+e(company_id)+'">Facts & conflicts</a> · <a href="/sources?company_id='+e(company_id)+'">Public source registry</a> · Report coverage remains incomplete.'
        return page(c['name'],f'<h1>{e(c["name"])}</h1>'+company_card(c)+f'<div class="card"><h2>Evidence & valuation</h2><p>{source}</p><p>No AI summary. No financial model has been calculated.</p><a class="button" href="/files?company_id={e(company_id)}">Upload evidence</a></div>',actor)

    @app.get('/models', response_class=HTMLResponse)
    def models_page(request: Request, q: str = ''):
        actor = actor_or_none(request)
        if not actor:
            return RedirectResponse('/login',status_code=303)
        body = '<h1>Model drafts</h1><p class="muted">Draft names and access settings. Use Templates for validated Excel structures. Financial calculations arrive later.</p><div class="card">'+form('/api/v1/models','Create private draft','<label>Draft title<input name="title" required maxlength="160"></label>')+'</div><div class="grid">'
        for m in list_models(request,q):
            controls = '' if m['owner_id'] != actor.id else form('/api/v1/models/'+m['id']+'/visibility','Make private' if m['shared'] else 'Share draft title with fund',hidden('shared',str(not m['shared']).lower())+hidden('revision',m['revision']),method='PATCH')
            body += f'<div class="card"><h2>{e(m["title"])}</h2><p>{"Shared with fund" if m["shared"] else "Private"} · Revision {m["revision"]}</p>{controls}</div>'
        return page('Models',body+'</div><p class="muted">Sharing exposes the draft title only. Revoking access cannot recall information already copied.</p>',actor)

    @app.get('/team', response_class=HTMLResponse)
    def team(request: Request):
        actor = actor_or_none(request)
        if not actor:
            return RedirectResponse('/login',status_code=303)
        entries = users(request)
        body = '<h1>Team accounts</h1><p class="muted">Account administrators cannot read colleagues’ private financial objects.</p><div class="card">'+form('/api/v1/users','Create analyst account','<label>Login<input name="login" required maxlength="120" autocomplete="off"></label><label>Initial password<input name="password" type="password" required minlength="12" maxlength="128" autocomplete="new-password"></label>')+'</div><div class="grid">'
        for u in entries:
            controls = '' if u['account_admin'] else form('/api/v1/users/'+u['id'],'Deactivate' if u['active'] else 'Activate',hidden('active',str(not u['active']).lower()),method='PATCH')
            body += f'<div class="card"><h2>{e(u["login"])}</h2><p>{"Active" if u["active"] else "Inactive"}</p>{controls}</div>'
        return page('Team',body+'</div>',actor)

"""Python-rendered lab workflow: source, reference, blind review, comparison."""
import json
from fastapi import Request,HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.models import Job,DocumentVersion,Document,Extraction,Company
from goldenstock.normalization import METRICS
from goldenstock.ai_lab import datasets,dataset,experiments,experiment,prepare_case,CaseRequest
from goldenstock.ai_resources_ui import device_choice,execution_cards


def mount_lab_ui(app):
    from goldenstock.ui import page,e,form,hidden,actor_or_none

    def field(label,name,value='',required=False):
        return f'<label>{e(label)}<input name="{e(name)}" value="{e(value or "")}" {"required" if required else ""}></label>'

    def select_field(label,name,values,current=None):
        return f'<label>{e(label)}<select name="{e(name)}" aria-label="{e(label)}">'+''.join(f'<option value="{e(key)}" {"selected" if key==current else ""}>{e(label)}</option>' for key,label in values)+'</select></label>'

    def sources(case):
        return ''.join(f'<article class="card"><strong>Evidence {n+1}</strong><blockquote>{e(item["text"])}</blockquote><p class="muted">{e(json.dumps(item.get("location",{})))} · Source SHA-256: {e(item["source_sha256"])}</p></article>' for n,item in enumerate(case['evidence']))

    @app.get('/lab')
    def home(request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        body='<h1>AI Lab</h1><p>Compare local models against your reference labels. Keep source documents separate between development and holdout.</p><div class="grid"><article class="card"><h2>1. Prepare a reference</h2><p>Select extracted evidence or reviewed company facts. Label expected metrics or relevant citations before running the models.</p><a class="button" href="/lab/new">Create a dataset</a></article><article class="card"><h2>2. Review blind answers</h2><p>The two local profiles run sequentially. Judge every successful answer before revealing model names.</p></article><article class="card"><h2>3. Compare results</h2><p>Precision, recall, context, citations and execution time are reported separately. A small test does not establish 95% accuracy.</p></article></div><h2>Your datasets</h2>'
        for d in datasets(request): body+=f'<p><a href="/lab/datasets/{e(d["id"])}">{e(d["title"])} · v{d["revision"]}</a> · {e(d["kind"])} · {e(d["split"])}</p>'
        body+='<p><a href="/lab/workbooks">Annotation workbooks and imports</a></p>'
        body+='<h2>Your experiments</h2>'
        for r in experiments(request): body+=f'<p><a href="/lab/experiments/{e(r["id"])}">Experiment {e(r["id"][:8])}</a> · {"Models revealed" if r["revealed"] else "Blind review"}</p>'
        return page('AI Lab',body,actor)

    @app.get('/lab/new')
    def new(request:Request,kind:str='proposals',job_id:str='',company_id:str='',offset:int=0,parent_id:str=''):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        if kind not in {'proposals','summary'} or not 0<=offset<=49999: raise HTTPException(422,'Invalid source selection')
        parent=dataset(parent_id,request) if parent_id else None
        expected=[];case=None
        if parent:
            if len(parent['snapshot']['cases'])!=1: raise HTTPException(409,'Use the dataset API to revise a multi-case dataset')
            case=parent['snapshot']['cases'][0];kind=parent['kind'];expected=case['expected']
            job_id=case['source']['job_id'] or '';company_id=case['source']['company_id'] or '';offset=case['source']['offset']
        body='<h1>Reference dataset</h1><p><a href="/lab">Back to AI Lab</a></p><p>Metrics use extracted originals; citation selection uses your currently accepted company facts. Source text remains untrusted data.</p>'
        with Session(request.app.state.engine) as db:
            jobs=list(db.execute(select(Job,DocumentVersion).join(DocumentVersion,Job.version_id==DocumentVersion.id).join(Document,Document.id==DocumentVersion.document_id).join(Extraction,Extraction.version_id==DocumentVersion.id).where(Document.org_id==actor.org_id,Document.owner_id==actor.id).order_by(DocumentVersion.created.desc()).limit(100)))
            companies=list(db.scalars(select(Company).order_by(Company.name)))
            if not parent:
                body+='<form method="get" action="/lab/new" class="card">'+select_field('Task','kind',[('proposals','Extract metrics'),('summary','Select citations')],kind)
                body+=select_field('Extracted original (metrics)','job_id',[('','Select an original')]+[(j.id,v.filename) for j,v in jobs],job_id)
                body+=select_field('Company (citations)','company_id',[('','Select a company')]+[(c.id,c.name) for c in companies],company_id)
                body+='<label>Evidence offset<input type="number" name="offset" min="0" max="49999" value="'+str(offset)+'"></label><button>Load evidence</button></form>'
                if (kind=='proposals' and job_id) or (kind=='summary' and company_id):
                    source=CaseRequest(job_id=job_id if kind=='proposals' else None,company_id=company_id if kind=='summary' else None,offset=offset,expected=[])
                    case=prepare_case(db,actor,kind,source)
        if not case: return page('Reference dataset',body,actor)
        body+='<h2>Source evidence</h2>'+sources(case)
        if not parent:
            draft_fields=hidden('kind',kind)+hidden('job_id',job_id if kind=='proposals' else '')+hidden('company_id',company_id if kind=='summary' else '')+hidden('offset',offset)
            draft_fields+=field('Workbook title','title','',True)+select_field('Workbook split','split',[('development','Development'),('holdout','Holdout')])
            body+='<h2>Annotate in XLSX</h2><p>Create an unlabelled workbook with these exact sources. No reference facts are accepted at this step. The source split is reserved for this analyst.</p>'
            body+=form('/api/v1/lab/exchange/drafts','Prepare annotation workbook',draft_fields).replace('<form ','<form data-lab-draft="true" ',1)
        fields=hidden('kind',kind)+hidden('job_id',job_id if kind=='proposals' else '')+hidden('company_id',company_id if kind=='summary' else '')+hidden('offset',offset)+hidden('parent_id',parent_id)
        fields+=field('Dataset title','title',parent['title'] if parent else '',True)
        fields+=select_field('Evaluation split','split',[('development','Development'),('holdout','Holdout — reserve for final comparison')],parent['split'] if parent else 'development')
        fields+='<p>Once a document belongs to a split it cannot move to the other one. Consumed holdout labels cannot be revised.</p><h2>Reference labels</h2>'
        if kind=='summary':
            for n,item in enumerate(case['evidence']): fields+=f'<label><input class="check" type="checkbox" name="expected" value="{e(item["id"])}" {"checked" if item["id"] in expected else ""}> Evidence {n+1} should appear in the summary</label>'
        else:
            fields+='<p>Enter only explicitly stated metrics. Leave unsupported context empty. Empty metric rows are ignored.</p>'
            for n in range(12):
                value=expected[n] if n<len(expected) else {};prefix=f'ref.{n}.'
                fields+=f'<details {"open" if n==0 or value else ""}><summary>Reference metric {n+1}</summary><fieldset>'
                fields+=select_field('Metric',prefix+'metric',[('','Unused row')]+[(k,v[0]) for k,v in METRICS.items()],value.get('metric'))
                fields+=select_field('Evidence',prefix+'evidence_id',[(item['id'],f'Evidence {i+1}') for i,item in enumerate(case['evidence'])],value.get('evidence_id'))
                for key,label in [('number_text','Reported numeric token'),('quote','Verbatim quote including number'),('currency','Currency'),('scale','Scale'),('period','Period'),('perimeter','Reporting perimeter'),('definition','Metric definition')]: fields+=field(label,prefix+key,value.get(key,''))
                fields+='</fieldset></details>'
        fields+='<label><input class="check" type="checkbox" name="reference_confirmed" required> I checked every reference against the evidence; an empty list means no relevant facts.</label>'
        body+='<div class="card">'+form('/api/v1/lab/datasets','Save immutable reference',fields).replace('<form ','<form data-lab-dataset="true" ',1)+'</div>'
        return page('Reference dataset',body,actor)

    @app.get('/lab/datasets/{key}')
    def dataset_page(key:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        d=dataset(key,request)
        body=f'<h1>{e(d["title"])}</h1><p>Version {d["revision"]} · {e(d["kind"])} · {e(d["split"])}</p><p><a href="/lab">AI Lab</a> · <a href="/lab/new?parent_id={e(key)}">Create a revised reference</a> · <a href="/api/v1/lab/datasets/{e(key)}">Reference receipt (JSON)</a></p>'
        body+='<div class="notice">Compare the two installed Qwen profiles in one sequential queue. Reviewers see anonymous variants until all successful answers have been judged. Holdout can be consumed by one configuration only.</div>'
        body+=form('/api/v1/lab/exchange/datasets/'+key,'Export labels to XLSX').replace('<form ','<form data-lab-exchange="true" ',1)
        body+=form('/api/v1/lab/experiments','Compare local models',hidden('dataset_id',key)).replace('<form ','<form data-lab-experiment="true" ',1)
        for n,case in enumerate(d['snapshot']['cases']):
            body+=f'<h2>Case {n+1}</h2>'+sources(case)+'<details><summary>Saved reference labels</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+e(json.dumps(case['expected'],indent=2))+'</pre></details>'
        return page('Dataset',body,actor)

    @app.get('/lab/experiments/{key}')
    def experiment_page(key:str,request:Request):
        actor=actor_or_none(request)
        if not actor: return RedirectResponse('/login',status_code=303)
        data=experiment(key,request);d=data['dataset'];snapshot=dataset(d['id'],request)['snapshot']
        body=f'<h1>{"Model comparison" if data["revealed"] else "Blind review"}</h1><p><a href="/lab">AI Lab</a> · <a href="/lab/datasets/{e(d["id"])}">{e(d["title"])} v{d["revision"]}</a> · {e(d["split"])}</p>'
        body+='<div class="notice">Technical comparison only. A real independent benchmark and the 95% target remain unconfirmed. Missing or failed answers reduce recall; unknown cost stays unknown.</div>'
        if data['revealed']:
            body+='<p>Execution devices and resource attempts are now visible below. Compare timing only for runs on the same device and comparable load; CPU and GPU timings are not interchangeable.</p>'
            body+='<div class="table-wrap" tabindex="0" aria-label="Model scores, scroll horizontally for all columns"><table class="sensitivity"><caption>Scores across all cases in this dataset</caption><thead><tr><th>Model</th><th>Precision</th><th>Recall</th><th>F1</th><th>Citations</th><th>Completed / failed</th><th>Seconds</th><th>Tokens</th></tr></thead><tbody>'
            def pct(value): return 'N/A' if value is None else f'{value:.1%}'
            for c in data['comparison']:
                m=c['metrics'];body+=f'<tr><th>{e(c["profile"])}</th><td>{pct(m["precision"])}</td><td>{pct(m["recall"])}</td><td>{pct(m["f1"])}</td><td>{pct(m["citation_precision"])}</td><td>{c["succeeded"]} / {c["failed"]}</td><td>{e(c["seconds"] if c["seconds"] is not None else "N/A")}</td><td>{e(c["tokens"] if c["tokens"] is not None else "N/A")}</td></tr>'
            body+='</tbody></table></div><p>Seconds cover successful provider calls; queue wait and failed-call time are not included. Monetary cost is not measured.</p>'
            for c in data['comparison']:
                body+=f'<p>{e(c["profile"])}: {c["metrics"]["matched"]} matched / {c["metrics"]["predicted"]} predicted / {c["metrics"]["expected"]} expected; human-correct answers {c["human_correct"]} / {c["succeeded"]}.</p>'
                if d['kind']=='proposals': body+='<p>Context accuracy among matched metrics: '+e(', '.join(k+' '+pct(v) for k,v in c['metrics']['context_accuracy'].items()))+'</p>'
            body+=f'<p><a href="/api/v1/lab/experiments/{e(key)}">Download comparison receipt (JSON)</a></p>'
        else:
            if any(r['state']=='awaiting_device' for r in data['runs']):
                body+=device_choice(f'/api/v1/lab/experiments/{key}',group=True)
            body+='<p>Reload for progress. Compare each answer with the source and reference; model identity and timing remain hidden.</p><div class="row">'
            for action,label in [('reveal','Reveal models and scores'),('cancel','Cancel pending variants'),('retry','Retry failed variants')]: body+=form(f'/api/v1/lab/experiments/{key}/{action}',label)
            body+='</div>'
        for r in data['runs']:
            case=snapshot['cases'][r['case']]
            display=r['spec']['profile'] if data['revealed'] else r['variant']
            body+=f'<article class="card"><h2>{e(display)} · Case {r["case"]+1}</h2><p>{e(r["state"])} · {e(r["error"])}</p><details><summary>Source evidence and reference</summary>'+sources(case)+'<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+e(json.dumps(case['expected'],indent=2))+'</pre></details>'
            for answer in r['output'].get('proposals',r['output'].get('claims',[])):
                body+='<blockquote>'+e(answer.get('quote',''))+'</blockquote>'
                if 'metric' in answer:
                    body+='<p><strong>'+e(METRICS.get(answer['metric'],(answer['metric'],))[0])+': '+e(answer['number_text'])+'</strong></p><p>'
                    body+=e(' · '.join(label+': '+(answer.get(k) or 'Not stated') for k,label in [('currency','Currency'),('scale','Scale'),('period','Period'),('perimeter','Perimeter'),('definition','Definition')]))+'</p>'
                body+='<details><summary>Evidence ID</summary><p>'+e(answer.get('evidence_id',''))+'</p></details>'
            if r['state']=='succeeded' and not r['output'].get('proposals',r['output'].get('claims',[])): body+='<p>No facts selected.</p>'
            for gap in r['output'].get('gaps',[]): body+='<p>Gap: '+e(gap)+'</p>'
            for a in r['annotations']: body+=f'<p>Review v{a["revision"]}: {e(a["verdict"])} — {e(a["reason"])}</p>'
            if data['revealed']: body+=execution_cards(r['executions'])
            if r['state']=='succeeded' and not data['revealed']:
                previous=r['annotations'][-1] if r['annotations'] else {}
                fields=hidden('revision',previous.get('revision',0))+select_field('Judgement','verdict',[(v,v.title()) for v in ('correct','incorrect','uncertain')],previous.get('verdict'))
                fields+=f'<label>Reason<textarea name="reason" minlength="5" maxlength="1000" required>{e(previous.get("reason",""))}</textarea></label>'
                body+=form(f'/api/v1/lab/experiments/{key}/runs/{r["id"]}/annotations','Save blind judgement',fields)
            body+='</article>'
        return page('AI Lab experiment',body,actor)

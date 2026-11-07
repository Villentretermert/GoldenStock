// Real UI smoke. Credentials are supplied only in the child process environment.
const {createRequire}=require('module');
const path=require('path');
const fs=require('fs');
const req=createRequire(path.join(process.env.GS_NODE_MODULES,'playwright','package.json'));
const {chromium}=req('playwright');
const base=process.env.GS_APP_URL||'http://127.0.0.1:8081';
if(new URL(base).hostname!=='127.0.0.1')throw Error('Smoke target must be loopback');
let browser;
(async()=>{
 browser=await chromium.launch({headless:true,channel:'chrome'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[],external=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
   const url=new URL(route.request().url());
   if(url.hostname!=='127.0.0.1'){external.push(url.hostname);return route.abort();}
   return route.continue();
 });
 fs.mkdirSync('design/previews',{recursive:true});
 await page.goto(base+'/',{waitUntil:'networkidle'});
 await page.getByLabel('Login',{exact:true}).fill(process.env.GS_QA_LOGIN);
 await page.getByLabel('Password',{exact:true}).fill(process.env.GS_QA_PASSWORD);
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByRole('heading',{name:'Your watchlist',exact:true}).waitFor();
 if(process.env.GS_QA_AI_BATCH_PDF){
   await page.goto(base+'/files?company_id=nu');
   const name='synthetic-selected-pages.pdf';
   await page.getByLabel('Original file').setInputFiles({name,mimeType:'application/pdf',buffer:Buffer.from(process.env.GS_QA_AI_BATCH_PDF,'base64')});
   await page.getByRole('button',{name:'Upload private original'}).click();
   const card=page.locator('div.card').filter({has:page.getByRole('heading',{name,exact:true})});
   await card.waitFor();
   for(const [role,title] of [['button','Extract English document'],['link','View extracted evidence']]){
     const action=card.getByRole(role,{name:title,exact:true});
     for(let attempt=0;attempt<40&&!await action.count();attempt++){
       await page.reload({waitUntil:'networkidle'});
       if(!await action.count())await new Promise(r=>setTimeout(r,750));
     }
     await action.click();
   }
   await page.goto(base+'/ai/nu');
   await page.getByLabel('First original page',{exact:true}).fill('2');
   await page.getByLabel('Last original page',{exact:true}).fill('3');
   await page.getByRole('button',{name:'Preview page batch',exact:true}).click();
   await page.getByText('2 AI requests',{exact:false}).waitFor();
   if((await page.locator('main').innerText()).includes('Excluded cover'))throw Error('Batch contains outside page');
   await page.locator('details summary').first().click();
   await page.screenshot({path:'design/previews/ai-batch-preview.png'});
   await page.setViewportSize({width:390,height:900});
   await page.screenshot({path:'design/previews/ai-batch-preview-mobile.png'});
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Batch preview overflow');
   await page.setViewportSize({width:1440,height:1000});
   await page.getByRole('button',{name:'Start selected-page batch',exact:true}).click();
   await page.waitForURL('**/ai-batch/*');
   const key=new URL(page.url()).pathname.split('/').pop();let batch;
   for(let attempt=0;attempt<180;attempt++){
     batch=await(await page.request.get(base+'/api/v1/ai/batches/'+key)).json();
     if(batch.completed===batch.total)break;
     await new Promise(r=>setTimeout(r,1000));
   }
   if(batch.state!=='succeeded'||batch.total!==2)throw Error('Batch failed: '+JSON.stringify(batch.runs));
   for(const part of batch.runs){
     const run=await(await page.request.get(base+'/api/v1/ai/runs/'+part.run_id)).json();
     if(run.source_window.evidence.some(e=>![2,3].includes(e.location.page)))throw Error('Wrong page reached AI');
     if(!run.result.proposals.length)throw Error('Synthetic part has no proposals');
   }
   await page.reload({waitUntil:'networkidle'});
   await page.screenshot({path:'design/previews/ai-batch-result.png'});
   await page.setViewportSize({width:390,height:900});
   await page.screenshot({path:'design/previews/ai-batch-result-mobile.png'});
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Batch result overflow');
   await page.setViewportSize({width:1440,height:1000});
   await page.getByRole('link',{name:'Part 1',exact:true}).click();
   await page.getByRole('link',{name:'Back to selected-page batch',exact:true}).waitFor();
   console.log('AI batch UI PASS: selected pages only, two local Qwen calls, frozen sources, progress and desktop/mobile.');
 }
 if(process.env.GS_QA_AI_WINDOW_PDF){
   await page.goto(base+'/files?company_id=nu');
   const name='synthetic-long-ai-page.pdf';
   await page.getByLabel('Original file').setInputFiles({name,mimeType:'application/pdf',buffer:Buffer.from(process.env.GS_QA_AI_WINDOW_PDF,'base64')});
   await page.getByRole('button',{name:'Upload private original'}).click();
   const card=page.locator('div.card').filter({has:page.getByRole('heading',{name,exact:true})});
   await card.waitFor();
   for(const [role,title] of [['button','Extract English document'],['link','View extracted evidence']]){
     const action=card.getByRole(role,{name:title,exact:true});
     for(let attempt=0;attempt<40&&!await action.count();attempt++){
       await page.reload({waitUntil:'networkidle'});
       if(!await action.count())await new Promise(r=>setTimeout(r,750));
     }
     await action.click();
   }
   await page.getByRole('link',{name:'Preview AI evidence',exact:true}).first().click();
   const previewText=await page.locator('.ai-source').allTextContents();
   const next=await page.getByRole('link',{name:'Preview next fragment',exact:true}).getAttribute('href');
   if(!next.includes('text_offset='))throw Error('No long-text continuation');
   await page.screenshot({path:'design/previews/ai-window-desktop.png'});
   await page.setViewportSize({width:390,height:900});
   await page.screenshot({path:'design/previews/ai-window-mobile.png'});
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('AI preview overflow');
   await page.setViewportSize({width:1440,height:1000});
   await page.getByRole('button',{name:'Suggest metrics from this fragment',exact:true}).click();
   await page.waitForURL('**/ai-run/*');
   const key=new URL(page.url()).pathname.split('/').pop();
   let run;
   for(let attempt=0;attempt<120;attempt++){
     run=await(await page.request.get(base+'/api/v1/ai/runs/'+key)).json();
     if(['failed','cancelled'].includes(run.state))throw Error('Window inference failed: '+run.error);
     if(run.state==='succeeded')break;
     await new Promise(r=>setTimeout(r,1000));
   }
   if(run.state!=='succeeded')throw Error('Window inference timeout');
   if(JSON.stringify(run.source_window.evidence.map(e=>e.text))!==JSON.stringify(previewText))throw Error('Saved source differs from preview');
   if(!run.result.proposals.some(p=>p.metric==='profit'&&p.number_text==='120'))throw Error('Synthetic profit missing');
   await page.reload({waitUntil:'networkidle'});
   await page.getByRole('link',{name:'Preview next fragment',exact:true}).click();
   if(page.url()!==base+next)throw Error('Wrong continuation');
   if((await page.locator('.ai-source').allTextContents()).includes(previewText[0]))throw Error('Repeated first window');
   await page.getByRole('link',{name:'Open full source item',exact:true}).first().click();
   await page.getByRole('heading',{name:'Normalize evidence',exact:true}).waitFor();
   console.log('AI window UI PASS: real local model on synthetic PDF, preview matches frozen input, next fragment, original, desktop/mobile.');
 }
 if(process.env.GS_QA_WORKBOOK){
   await page.goto(base+'/files?company_id=jpm');
   const name='synthetic-compact-book.xlsx';
   await page.getByLabel('Original file').setInputFiles({name,mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:Buffer.from(process.env.GS_QA_WORKBOOK,'base64')});
   await page.getByRole('button',{name:'Upload private original'}).click();
   const card=page.locator('div.card').filter({has:page.getByRole('heading',{name,exact:true})});
   await card.waitFor();
   for(const [role,title] of [['button','Extract English document'],['link','View extracted evidence']]){
     const action=card.getByRole(role,{name:title,exact:true});
     for(let attempt=0;attempt<30&&!await action.count();attempt++){
       await page.reload({waitUntil:'networkidle'});
       if(!await action.count())await new Promise(r=>setTimeout(r,700));
     }
     await action.click();
   }
   await page.getByText('Worksheet ranges',{exact:true}).click();
   await page.getByText('Appendix · A1:Z1000 · hidden · 0 merged ranges',{exact:true}).waitFor();
   await page.locator('details').filter({hasText:'Worksheet ranges'}).screenshot({path:'design/previews/compact-workbook.png'});
   if(await page.locator('tbody tr').count()!==5)throw Error('Unexpected compact workbook item count');
   console.log('Compact workbook UI PASS: original, verified job, five source cells and sheet layout.');
 }
 if(process.env.GS_QA_PDF_CHUNKS==='1'){
   await page.goto(base+'/files');
   const card=page.locator('div.card').filter({has:page.getByRole('heading',{name:'synthetic-pdf-progress.pdf',exact:true})});
   await card.getByText('Incomplete extraction: 25 / 26',{exact:false}).waitFor();
   if(await card.getByRole('link',{name:'View extracted evidence'}).count())throw Error('Partial evidence exposed');
   await page.screenshot({path:'design/previews/pdf-progress-desktop.png',fullPage:true});
   await page.setViewportSize({width:390,height:900});
   await page.screenshot({path:'design/previews/pdf-progress-mobile.png',fullPage:true});
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('PDF progress overflow');
   await page.setViewportSize({width:1440,height:1000});
   await card.getByRole('button',{name:'Retry processing',exact:true}).click();
   for(let attempt=0;attempt<30;attempt++){
     await page.reload({waitUntil:'networkidle'});
     if(await card.getByRole('link',{name:'View extracted evidence'}).count())break;
     await new Promise(r=>setTimeout(r,1000));
   }
   await card.getByRole('link',{name:'View extracted evidence'}).click();
   await page.getByText('Complete PDF: 26 original pages',{exact:false}).waitFor();
   await page.getByText('Synthetic browser page 26',{exact:false}).waitFor();
   await page.screenshot({path:'design/previews/pdf-complete-desktop.png',fullPage:true});
   await page.getByLabel('Original PDF page',{exact:true}).fill('26');
   await page.getByRole('button',{name:'Go to page',exact:true}).click();
   await page.getByRole('link',{name:'Normalize',exact:true}).first().click();
   await page.getByRole('heading',{name:'Original evidence · Original PDF page 26'}).waitFor();
   await page.getByLabel('Exact number from this evidence').fill('213,000');
   const next=page.getByRole('button',{name:'Find next occurrence'});
   await next.click();
   await page.locator('#chosen-row').filter({hasText:'Total assets'}).waitFor();
   await next.click();
   await page.locator('#chosen-row').filter({hasText:'Total liabilities and equity'}).waitFor();
   const chosen=await page.locator('input[name="source_start"]').inputValue();
   if(+chosen!==(await page.locator('#mapping-evidence').textContent()).lastIndexOf('213,000'))throw Error('Wrong chosen source position');
   await page.locator('#chosen-row').screenshot({path:'design/previews/source-occurrence.png'});
   await page.getByLabel('Exact number from this evidence').fill('198,000');
   if(!(await page.locator('input[name="source_start"]').isDisabled()))throw Error('Edited amount retained old position');
   await next.click();
   await saveMappedFact('assets','millions','Total group assets','instant');
   await page.goto(base+'/review/jpm');
   await page.locator('article mark').filter({hasText:'198,000'}).waitFor();
   await page.getByText('Status: unreviewed',{exact:true}).waitFor();
   console.log('PDF UI PASS: private partial progress, mobile layout, retry and 26 original pages.');
 }
 await page.getByRole('link',{name:'Companies',exact:true}).click();
 const sber=page.locator('article').filter({has:page.getByRole('heading',{name:'Sberbank',exact:true})});
 await sber.getByRole('button',{name:'Add to watchlist'}).click();
 await sber.getByRole('button',{name:'Remove from watchlist'}).waitFor();
 await page.getByRole('link',{name:'Watchlist',exact:true}).click();
 await page.getByRole('heading',{name:'Sberbank',exact:true}).waitFor();
 await page.screenshot({path:'design/previews/workspace-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:900});
 await page.screenshot({path:'design/previews/workspace-mobile.png',fullPage:true});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 await page.setViewportSize({width:1440,height:1000});
 await page.goto(base+'/sources?company_id=sber',{waitUntil:'networkidle'});
 await page.getByRole('heading',{name:'Public sources',exact:true}).waitFor();
 if(!await page.getByText('English: unverified',{exact:false}).count())throw Error('English gap missing');
 await page.screenshot({path:'design/previews/sources-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:900});
 await page.screenshot({path:'design/previews/sources-mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Source page mobile overflow');
 await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('link',{name:'Models',exact:true}).click();
 await page.getByLabel('Draft title').fill('Synthetic QA draft');
 await page.getByRole('button',{name:'Create private draft'}).click();
 await page.getByRole('heading',{name:'Synthetic QA draft'}).waitFor();
 await page.getByRole('button',{name:'Share draft title with fund'}).click();
 await page.getByRole('button',{name:'Make private',exact:true}).waitFor();
 await page.getByRole('link',{name:'Files & jobs',exact:true}).click();
 await page.getByLabel('Company',{exact:true}).selectOption('sber');
 const pdf=Buffer.from(process.env.GS_QA_PDF,'base64');
 await page.getByLabel('Original file').setInputFiles({name:'synthetic-browser-check.pdf',mimeType:'application/pdf',buffer:pdf});
 await page.getByRole('button',{name:'Upload private original'}).click();
 await page.getByRole('heading',{name:'synthetic-browser-check.pdf'}).waitFor();
 const docs=await (await page.request.get(base+'/api/v1/documents')).json();
 const uploaded=docs.find(d=>d.filename==='synthetic-browser-check.pdf');
 const version=uploaded.versions[0];
 let job;
 for(let attempt=0;attempt<30;attempt++){
   job=await (await page.request.get(base+'/api/v1/jobs/'+version.job_id)).json();
   if(job.state==='succeeded')break;
   await new Promise(r=>setTimeout(r,1000));
 }
 if(job.state!=='succeeded')throw Error('Worker did not complete verification');
 await page.reload({waitUntil:'networkidle'});
 await page.screenshot({path:'design/previews/files-desktop.png',fullPage:true});
 const download=await page.request.get(base+`/api/v1/documents/${uploaded.id}/versions/${version.version_id}/download`);
 if(download.status()!==200||!(await download.body()).equals(pdf))throw Error('Original download mismatch');
 await page.getByRole('button',{name:'Extract English document'}).click();
 for(let attempt=0;attempt<30;attempt++){
   job=await (await page.request.get(base+'/api/v1/jobs/'+version.job_id)).json();
   if(job.kind==='extract_document' && job.state==='succeeded')break;
   if(job.state==='failed')throw Error('Extraction failed: '+job.error_code);
   await new Promise(r=>setTimeout(r,1000));
 }
 await page.reload({waitUntil:'networkidle'});
 await page.locator('div.card').filter({has:page.getByRole('heading',{name:'synthetic-browser-check.pdf',exact:true})}).getByRole('link',{name:'View extracted evidence'}).click();
 await page.getByRole('heading',{name:'Extracted evidence'}).waitFor();
 await page.getByText('Profit: -120 USD million. Footnote 1.',{exact:true}).waitFor();
 await page.screenshot({path:'design/previews/extraction-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:900});
 await page.screenshot({path:'design/previews/extraction-mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Extraction page overflow');
 await page.setViewportSize({width:1440,height:1000});
 async function mapFact(scale){
   await page.goto(base+'/normalize/'+version.job_id+'/0');
   await page.getByLabel('Exact number from this evidence').fill('-120');
   await saveMappedFact('profit',scale,'Total profit after tax','year');
 }
 async function saveMappedFact(metric,scale,definition,period){
   await page.getByLabel('Metric',{exact:true}).selectOption(metric);
   await page.getByLabel('Reported unit').selectOption('money');
   await page.getByLabel('Reported scale').selectOption(scale);
   await page.getByLabel('Currency code',{exact:false}).fill('USD');
   await page.getByLabel('Period kind').selectOption(period);
   if(period==='year')await page.getByLabel('Period start',{exact:false}).fill('2025-01-01');
   await page.getByLabel('Period end').fill(period==='year'?'2025-12-31':'2024-12-31');
   await page.getByLabel('Reporting perimeter').selectOption('group');
   await page.getByLabel('Exact entities / segment included').fill('Synthetic consolidated group');
   await page.getByLabel('Accounting basis').selectOption('IFRS');
   await page.getByLabel('Metric definition:',{exact:false}).fill(definition);
   await page.getByLabel('Disclosure version').selectOption('original');
   await page.getByRole('button',{name:'Save unreviewed fact'}).click();
   await page.getByRole('heading',{name:'Facts & conflicts',exact:true}).waitFor();
 }
 await mapFact('millions');
 await mapFact('thousands'); // Deliberate synthetic context error must be visible.
 await page.getByText('1 blocking discrepancies',{exact:false}).waitFor();
 await page.screenshot({path:'design/previews/facts-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:900});
 await page.screenshot({path:'design/previews/facts-mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Facts page overflow');
 await page.setViewportSize({width:1440,height:1000});
 await page.goto(base+'/review/sber');
 const facts=await(await page.request.get(base+'/api/v1/facts?company_id=sber')).json();
 async function reviewFact(f,decision){
   const card=page.locator('#review-'+f.id);
   await card.getByLabel('Decision',{exact:true}).selectOption(decision);
   await card.getByLabel('Reason / checked warnings').fill('Synthetic check against original scale');
   await card.getByRole('button',{name:'Record decision'}).click();
   await page.waitForLoadState('networkidle');
   await card.getByText('Status: '+decision,{exact:true}).waitFor();
 }
 for(const f of facts) await reviewFact(f,'accepted');
 await page.getByLabel('Input set title').fill('Synthetic verified input set');
 await page.getByRole('button',{name:'Save verified input set'}).click();
 await page.getByRole('alert').filter({hasText:'resolve profit/equity conflicts'}).waitFor();
 await reviewFact(facts.find(f=>f.scale==='thousands'),'rejected');
 await page.getByLabel('Input set title').fill('Synthetic verified input set');
 await page.getByRole('button',{name:'Save verified input set'}).click();
 await page.getByRole('link',{name:'Synthetic verified input set',exact:true}).waitFor();
 await page.screenshot({path:'design/previews/review-desktop.png',fullPage:true});
 await page.locator('#review-'+facts.find(f=>f.scale==='millions').id).screenshot({path:'design/previews/review-fact.png'});
 await page.setViewportSize({width:390,height:900});
 await page.screenshot({path:'design/previews/review-mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Review page overflow');
 await page.setViewportSize({width:1440,height:1000});
 if(process.env.GS_QA_AI==='1'){
   await page.goto(base+'/ai/sber');
   await page.getByRole('button',{name:'Preview evidence',exact:true}).click();
   await page.getByRole('button',{name:'Suggest metrics from this fragment',exact:true}).click();
   await page.waitForLoadState('networkidle');
   async function waitAI(kind){
     let result;
     for(let i=0;i<120;i++){
       const runs=await(await page.request.get(base+'/api/v1/ai/runs?company_id=sber')).json();
       result=runs.find(r=>r.kind===kind);
       if(result && ['failed','cancelled'].includes(result.state))throw Error('AI task: '+result.error);
       if(result?.state==='succeeded')return result;
       await new Promise(r=>setTimeout(r,2000));
     }
     throw Error('AI task timeout');
   }
   const proposal=await waitAI('proposals');
   if(!proposal.result.proposals.length)throw Error('No proposal for synthetic profit');
   await page.goto(base+'/ai-run/'+proposal.id);
   await page.screenshot({path:'design/previews/ai-proposal.png',fullPage:true});
   await page.goto(base+'/ai/sber');
   await page.getByRole('button',{name:'Create summary',exact:true}).click();
   await page.waitForLoadState('networkidle');
   const summary=await waitAI('summary');
   if(!summary.result.claims.length)throw Error('No claims for confirmed synthetic profit');
   await page.goto(base+'/ai-run/'+summary.id);
   await page.screenshot({path:'design/previews/ai-summary.png',fullPage:true});
   await page.setViewportSize({width:390,height:900});
   await page.screenshot({path:'design/previews/ai-summary-mobile.png',fullPage:true});
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('AI page overflow');
   await page.setViewportSize({width:1440,height:1000});
   await page.goto(base+'/review/sber');
 }
 if(process.env.GS_QA_PUBLIC==='1'){
   for(const company of ['jpm','hsbc','nu']){
     await page.goto(base+'/ai/'+company);
     await page.getByRole('button',{name:'Research SEC and summarize',exact:true}).click();
     let run;
     for(let i=0;i<150;i++){
       const runs=await(await page.request.get(base+'/api/v1/ai/runs?company_id='+company)).json();
       run=runs.find(r=>r.kind==='public_summary');
       if(run?.state==='failed')throw Error('Public summary failed: '+run.error);
       if(run?.state==='succeeded')break;
       await new Promise(r=>setTimeout(r,2000));
     }
     if(run?.state!=='succeeded'||!run.result.claims.length)throw Error('Missing public summary '+company);
     await page.goto(base+'/ai-run/'+run.id);
     const detail=await(await page.request.get(base+'/api/v1/ai/runs/'+run.id)).json();
     const original=await page.request.get(base+'/api/v1/public-snapshots/'+detail.snapshot_id+'/download');
     if(original.status()!==200)throw Error('Original SEC download failed');
     await page.screenshot({path:'design/previews/public-'+company+'.png',fullPage:true});
     if(run.result.claims.some(c=>c.text!==c.quote))throw Error('Unsafe numeric paraphrase');
     console.log(JSON.stringify({company,claims:run.result.claims.length,seconds:run.result.seconds,prompt:run.result.prompt_version}));
   }
   await page.goto(base+'/review/sber');
 }
 if(process.env.GS_QA_LAB==='1'){
   for(const kind of ['proposals','summary']){
     await page.goto(base+'/lab/new');
     await page.getByLabel('Task',{exact:true}).selectOption(kind);
     if(kind==='proposals')await page.getByLabel('Extracted original (metrics)',{exact:true}).selectOption(version.job_id);
     else await page.getByLabel('Company (citations)',{exact:true}).selectOption('sber');
     await page.getByRole('button',{name:'Load evidence',exact:true}).click();
     await page.getByRole('heading',{name:'Source evidence',exact:true}).waitFor();
     await page.getByLabel('Dataset title',{exact:true}).fill('Synthetic '+kind+' lab reference');
     if(kind==='proposals'){
       const ref=page.locator('fieldset').first();
       await ref.getByLabel('Metric',{exact:true}).selectOption('profit');
       await ref.getByLabel('Reported numeric token').fill('-120');
       await ref.getByLabel('Verbatim quote including number').fill('Profit: -120 USD million. Footnote 1.');
       await ref.getByLabel('Currency',{exact:true}).fill('USD');
       await ref.getByLabel('Scale',{exact:true}).fill('million');
     } else await page.getByLabel('Evidence 1 should appear in the summary',{exact:true}).check();
     await page.getByLabel('I checked every reference',{exact:false}).check();
     await page.getByRole('button',{name:'Save immutable reference',exact:true}).click();
     await page.getByRole('button',{name:'Compare local models',exact:true}).waitFor();
     await page.getByRole('button',{name:'Compare local models',exact:true}).click();
     await page.getByRole('heading',{name:'Blind review',exact:true}).waitFor();
     const id=new URL(page.url()).pathname.split('/').pop();let experiment;
     for(let i=0;i<240;i++){
       experiment=await(await page.request.get(base+'/api/v1/lab/experiments/'+id)).json();
       if(experiment.runs.every(r=>['succeeded','failed','cancelled'].includes(r.state)))break;
       await new Promise(r=>setTimeout(r,1000));
     }
     if(experiment.runs.some(r=>r.state!=='succeeded'))throw Error('Lab inference failed: '+JSON.stringify(experiment.runs.map(r=>({state:r.state,error:r.error}))));
     if(JSON.stringify(experiment).includes('qwen'))throw Error('Blind API revealed model names');
     await page.reload({waitUntil:'networkidle'});
     if((await page.locator('main').innerText()).includes('qwen'))throw Error('Blind UI revealed model names');
     await page.screenshot({path:'design/previews/lab-blind-'+kind+'.png',fullPage:true});
     for(let i=0;i<2;i++){
       const form=page.locator('form[data-api$="/annotations"]').nth(i);
       await form.getByLabel('Judgement',{exact:true}).selectOption('uncertain');
       await form.getByLabel('Reason',{exact:true}).fill('Synthetic automated UI check; independent human review still required.');
       await form.getByRole('button',{name:'Save blind judgement',exact:true}).click();
       await page.waitForLoadState('networkidle');
       await page.locator('article.card').filter({hasText:'Variant '+(i+1)+' · Case 1'}).getByText('Review v1:',{exact:false}).waitFor();
     }
     await page.getByRole('button',{name:'Reveal models and scores',exact:true}).click();
     await page.getByRole('heading',{name:'Model comparison',exact:true}).waitFor();
     experiment=await(await page.request.get(base+'/api/v1/lab/experiments/'+id)).json();
     if(experiment.comparison.length!==2||experiment.quality_target_confirmed)throw Error('Invalid comparison receipt');
     console.log(JSON.stringify({lab:kind,comparison:experiment.comparison}));
     await page.screenshot({path:'design/previews/lab-'+kind+'-desktop.png',fullPage:true});
     await page.setViewportSize({width:390,height:900});
     await page.screenshot({path:'design/previews/lab-'+kind+'-mobile.png',fullPage:true});
     if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Lab mobile overflow');
     await page.setViewportSize({width:1440,height:1000});
   }
   await page.goto(base+'/review/sber');
 }
 await reviewFact(facts.find(f=>f.scale==='millions'),'unreviewed');
 await page.getByText('Stale — review changes',{exact:false}).waitFor();
 if(process.env.GS_QA_TEMPLATES==='1'){
   await page.goto(base+'/templates');
   const demo=await(await page.request.get(base+'/api/v1/templates/demo')).body();
   await page.getByLabel('Template title',{exact:true}).fill('Synthetic five-year template');
   await page.getByLabel('XLSX template',{exact:true}).setInputFiles({name:'demo.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:demo});
   await page.getByRole('button',{name:'Validate and save template',exact:true}).click();
   await page.getByRole('link',{name:'Synthetic five-year template',exact:true}).click();
   await page.getByRole('heading',{name:'Version 1',exact:true}).waitFor();
   await page.getByRole('button',{name:'Share clean structure with fund',exact:true}).click();
   await page.getByRole('button',{name:'Make private',exact:true}).waitFor();
   await page.screenshot({path:'design/previews/template-desktop.png',fullPage:true});
   await page.setViewportSize({width:390,height:900});
   await page.screenshot({path:'design/previews/template-mobile.png',fullPage:true});
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Template page overflow');
   await page.setViewportSize({width:1440,height:1000});
   const original=await page.request.get(base+await page.getByRole('link',{name:'Download private original',exact:true}).getAttribute('href'));
   if(!(await original.body()).equals(demo))throw Error('Template original changed');
   if(process.env.GS_QA_CALCULATIONS==='1'){
     await page.getByRole('link',{name:'Calculate this version',exact:true}).click();
     await page.getByLabel('Calculation title',{exact:true}).fill('Synthetic calculation - not issuer data');
     for(const [name,growth] of [['base','0.05'],['optimistic','0.1'],['stress','0']]){
       if(name!=='base')await page.locator('[name="enable.'+name+'"]').check();
       await page.locator('[name="'+name+'.profit_owners.value"]').fill('100');
       await page.locator('[name="'+name+'.profit_owners.note"]').fill('Synthetic known-answer fixture');
       await page.locator('[name="'+name+'.growth.value"]').fill(growth);
       await page.locator('[name="'+name+'.growth.note"]').fill('Synthetic scenario assumption');
     }
     await page.locator('[name="confirmed"]').check();
     await page.screenshot({path:'design/previews/calculation-inputs.png',fullPage:true});
     await page.getByRole('button',{name:'Calculate and save private scenarios',exact:true}).click();
     await page.getByRole('heading',{name:'Synthetic calculation - not issuer data',exact:true}).waitFor();
     await page.getByRole('cell',{name:'127.63',exact:true}).waitFor();
     await page.getByRole('cell',{name:'161.05',exact:true}).waitFor();
     const savedUrl=page.url();
     await page.getByRole('button',{name:'Verify reproducibility',exact:true}).click();
     await page.getByRole('status').filter({hasText:'Replay matched'}).waitFor();
     await page.screenshot({path:'design/previews/calculation-desktop.png',fullPage:true});
     await page.setViewportSize({width:390,height:900});
     await page.screenshot({path:'design/previews/calculation-mobile.png',fullPage:true});
     if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Calculation page overflow');
     const runId=new URL(savedUrl).pathname.split('/').pop();
     const receipt=await(await page.request.get(base+'/api/v1/calculations/'+runId)).json();
     if(receipt.result.state!=='calculated_without_checks'||Object.keys(receipt.result.scenarios).length!==3)throw Error('Incorrect scenario receipt');
     await page.setViewportSize({width:1440,height:1000});
     if(process.env.GS_QA_VALUATIONS==='1'){
       for(const method of ['pe','pb','ddm','fcfe']){
         await page.goto(base+'/valuations/new?calculation_id='+runId+'&method='+method+(method==='pe'?'&operating=true':''));
         await page.getByLabel('Valuation title',{exact:true}).fill('Synthetic '+method.toUpperCase()+' - not issuer data');
         for(const name of ['method_note','scope_note','shares_note'])await page.locator('[name="'+name+'"]').fill('Synthetic method, perimeter and common-share basis checked for QA');
         await page.locator('[name="'+(['pe','pb'].includes(method)?'comparability_confirmed':'capital_confirmed')+'"]').check();
         let values={shares:'10'};
         if(method==='pe')values={...values,profit_owners:'100',preferred_dividends:'10',multiple:'10',monthly_revenue:'1000',mau:'100',cohort_start:'100',cohort_retained:'80',contribution_margin:'0.5',monthly_discount:'0.1'};
         else if(method==='pb')values={...values,equity_total:'1000',equity_nci:'100',equity_preferred:'100',multiple:'1.5'};
         else values={...values,cash_1:'100',cash_2:'100',cash_3:'100',cash_4:'100',cash_5:'100',cost_equity:'0.1',terminal_growth:'0'};
         if(method==='pe'){
           await page.locator('[name="operating_month"]').fill('2025-12');
           await page.locator('[name="operating_note"]').fill('Synthetic monthly activity, cohort and constant contribution assumptions');
         }
         for(const name of (method==='pe'?['base','optimistic','stress']:['base'])){
           if(name!=='base')await page.locator('[name="enable.'+name+'"]').check();
           for(const [key,value] of Object.entries(values)){
             if(method==='pe'&&key==='profit_owners')await page.locator('[name="'+name+'.'+key+'.source_key"]').selectOption('profit_owners');
             else await page.locator('[name="'+name+'.'+key+'.value"]').fill(value);
             await page.locator('[name="'+name+'.'+key+'.note"]').fill('Synthetic confirmed input and scope');
           }
         }
         await page.getByText('Optional ordinary-share quote for upside comparison',{exact:true}).click();
         await page.locator('[name="quote_price"]').fill('60');
         await page.locator('[name="quote_date"]').fill('2025-12-31');
         await page.locator('[name="quote_instrument"]').fill('Synthetic common share');
         await page.locator('[name="quote_source"]').fill('Synthetic known-answer fixture, not market data');
         await page.locator('[name="method_confirmed"]').check();
         await page.getByRole('button',{name:'Calculate and save equity valuation',exact:true}).click();
         await page.getByRole('heading',{name:'Synthetic '+method.toUpperCase()+' - not issuer data',exact:true}).waitFor();
         const valId=new URL(page.url()).pathname.split('/').pop();
         const val=await(await page.request.get(base+'/api/v1/valuations/'+valId)).json();
         const expected=method==='pe'?'90.00':method==='pb'?'120.00':'100.00';
         if(val.result.state!=='calculated'||val.result.scenarios.base.values.per_share.display!==expected)throw Error('Valuation mismatch '+method);
         if(method==='pe'&&val.result.scenarios.base.values.ltv_contribution.display!=='16.67')throw Error('LTV mismatch');
         await page.getByRole('button',{name:'Verify valuation reproducibility',exact:true}).click();
         await page.getByRole('status').filter({hasText:'Valuation replay matched'}).waitFor();
         if(process.env.GS_QA_EXPORTS==='1'&&['pe','ddm'].includes(method)){
           await require('node:fs/promises').mkdir('.build-browser-exports',{recursive:true});
           for(const kind of ['xlsx','pdf','pptx']){
             const pending=page.waitForEvent('download');
             await page.getByRole('link',{name:'Download '+kind.toUpperCase(),exact:true}).click();
             const file=await pending;
             if(await file.failure())throw Error('Export download failed '+kind);
             if(file.suggestedFilename()!=='GoldenStock-'+valId+'.'+kind)throw Error('Unexpected export filename');
             await file.saveAs('.build-browser-exports/'+method+'.'+kind);
           }
         }
         if(method==='ddm'){
           await page.screenshot({path:'design/previews/valuation-desktop.png',fullPage:true});
           await page.setViewportSize({width:390,height:900});
           await page.screenshot({path:'design/previews/valuation-mobile.png',fullPage:true});
           if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Valuation page overflow');
           await page.setViewportSize({width:1440,height:1000});
         }
       }
     }
     if(process.env.GS_QA_VALUATIONS==='1'){
       await page.goto(base+'/company/'+receipt.company_id);
       await page.getByRole('link',{name:'Open saved valuation (FCFE)',exact:true}).waitFor();
     }
     await page.goto(base+'/templates/'+receipt.input.template.id);
   }
   await page.getByRole('button',{name:'Create private structure copy',exact:true}).click();
   await page.getByRole('link',{name:'Copy of Synthetic five-year template',exact:true}).waitFor();
 }
 if(process.env.GS_QA_LAB==='1')console.log('AI Lab browser PASS: reference forms, two tasks / two local models, blind review, reveal, desktop/mobile.');
 if(process.env.GS_QA_MONITOR==='1'){
   const monitorStarted=Date.now()/1000;
   await page.goto(base+'/updates');
   await page.getByRole('heading',{name:'Reporting updates',exact:true}).waitFor();
   for(const name of ['JPMorgan Chase & Co.','HSBC Holdings plc','Nu Holdings Ltd.']){
     const card=page.locator('article.card').filter({has:page.getByRole('heading',{name,exact:true})});
     await card.getByRole('button',{name:'Follow reporting',exact:true}).click();
     await page.waitForLoadState('networkidle');
   }
   let status;
   for(let attempt=0;attempt<150;attempt++){
     status=await(await page.request.get(base+'/api/v1/monitoring')).json();
     const sources=status.companies.filter(c=>['jpm','hsbc','nu'].includes(c.company_id)).flatMap(c=>c.sources);
     if(sources.every(s=>s.last_attempt!==null)){
       if(sources.some(s=>s.error&&s.last_attempt>=monitorStarted))throw Error('Live SEC monitoring: '+JSON.stringify(sources.map(s=>({id:s.id,error:s.error}))));
       if(sources.every(s=>s.last_success!==null&&!s.error))break;
     }
     await new Promise(r=>setTimeout(r,1000));
   }
   const sources=status.companies.filter(c=>['jpm','hsbc','nu'].includes(c.company_id)).flatMap(c=>c.sources);
   if(sources.length!==6||sources.some(s=>!s.last_success||s.error))throw Error('Live monitor baseline incomplete');
   for(const s of sources){const source=await page.request.get(base+'/api/v1/monitor-snapshots/'+s.snapshot_id+'/download');if(source.status()!==200)throw Error('Source snapshot download failed');}
   await page.reload({waitUntil:'networkidle'});
   await page.screenshot({path:'design/previews/monitor-live.png',fullPage:true});
   console.log(JSON.stringify({monitoring:'six live SEC sources passed',sources:sources.map(s=>({id:s.id,known_items:s.known_items}))}));
 }
 await page.getByRole('link',{name:'Team',exact:true}).click();
 await page.getByRole('heading',{name:'Team accounts'}).waitFor();
 await page.getByRole('button',{name:'Sign out',exact:true}).click();
 await page.getByRole('button',{name:'Sign in',exact:true}).waitFor();
 if((await page.request.get(base+'/api/v1/documents')).status()!==401)throw Error('Logout did not revoke access');
 const ready=await page.request.get(base+'/health/ready');
 if(ready.status()!==200||errors.length||external.length||overflow)throw Error(JSON.stringify({ready:ready.status(),errors,external,overflow}));
 console.log(JSON.stringify({ready:200,scenarios:['login','watchlist','public sources','shared draft','private upload','worker success','download','extraction','normalization','conflicts','review','input snapshot','stale snapshot','team','logout',...(process.env.GS_QA_AI==='1'?['local AI proposal','source-backed summary','AI mobile']:[]),...(process.env.GS_QA_PUBLIC==='1'?['SEC JPMorgan summary','SEC HSBC summary','SEC Nu summary']:[]),...(process.env.GS_QA_VALUATIONS==='1'?['P/E and user economics','P/B equity reconciliation','DDM sensitivity','FCFE valuation','valuation replay','valuation mobile']:[]),...(process.env.GS_QA_EXPORTS==='1'?['XLSX download','PDF download','PPTX download']:[]),...(process.env.GS_QA_CALCULATIONS==='1'?['three calculation scenarios','replay verification','calculation mobile']:[]),...(process.env.GS_QA_TEMPLATES==='1'?['template upload','template sharing','template copy','template mobile']:[])],jsErrors:errors,externalRequests:external,mobileOverflow:overflow}));
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{await browser?.close();});

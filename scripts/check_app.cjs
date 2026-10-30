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
 const version=docs[0].versions[0];
 let job;
 for(let attempt=0;attempt<30;attempt++){
   job=await (await page.request.get(base+'/api/v1/jobs/'+version.job_id)).json();
   if(job.state==='succeeded')break;
   await new Promise(r=>setTimeout(r,1000));
 }
 if(job.state!=='succeeded')throw Error('Worker did not complete verification');
 await page.reload({waitUntil:'networkidle'});
 await page.screenshot({path:'design/previews/files-desktop.png',fullPage:true});
 const download=await page.request.get(base+`/api/v1/documents/${docs[0].id}/versions/${version.version_id}/download`);
 if(download.status()!==200||!(await download.body()).equals(pdf))throw Error('Original download mismatch');
 await page.getByRole('button',{name:'Extract English document'}).click();
 for(let attempt=0;attempt<30;attempt++){
   job=await (await page.request.get(base+'/api/v1/jobs/'+version.job_id)).json();
   if(job.kind==='extract_document' && job.state==='succeeded')break;
   if(job.state==='failed')throw Error('Extraction failed: '+job.error_code);
   await new Promise(r=>setTimeout(r,1000));
 }
 await page.reload({waitUntil:'networkidle'});
 await page.getByRole('link',{name:'View extracted evidence'}).click();
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
   await page.getByLabel('Metric',{exact:true}).selectOption('profit');
   await page.getByLabel('Reported unit').selectOption('money');
   await page.getByLabel('Reported scale').selectOption(scale);
   await page.getByLabel('Currency code',{exact:false}).fill('USD');
   await page.getByLabel('Period kind').selectOption('year');
   await page.getByLabel('Period start',{exact:false}).fill('2025-01-01');
   await page.getByLabel('Period end').fill('2025-12-31');
   await page.getByLabel('Reporting perimeter').selectOption('group');
   await page.getByLabel('Exact entities / segment included').fill('Synthetic consolidated group');
   await page.getByLabel('Accounting basis').selectOption('IFRS');
   await page.getByLabel('Metric definition:',{exact:false}).fill('Total profit after tax');
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
   await page.getByRole('button',{name:'Suggest metrics',exact:true}).click();
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
 await page.getByRole('link',{name:'Team',exact:true}).click();
 await page.getByRole('heading',{name:'Team accounts'}).waitFor();
 await page.getByRole('button',{name:'Sign out',exact:true}).click();
 await page.getByRole('button',{name:'Sign in',exact:true}).waitFor();
 if((await page.request.get(base+'/api/v1/documents')).status()!==401)throw Error('Logout did not revoke access');
 const ready=await page.request.get(base+'/health/ready');
 if(ready.status()!==200||errors.length||external.length||overflow)throw Error(JSON.stringify({ready:ready.status(),errors,external,overflow}));
 console.log(JSON.stringify({ready:200,scenarios:['login','watchlist','public sources','shared draft','private upload','worker success','download','extraction','normalization','conflicts','review','input snapshot','stale snapshot','team','logout',...(process.env.GS_QA_AI==='1'?['local AI proposal','source-backed summary','AI mobile']:[]),...(process.env.GS_QA_PUBLIC==='1'?['SEC JPMorgan summary','SEC HSBC summary','SEC Nu summary']:[]),...(process.env.GS_QA_VALUATIONS==='1'?['P/E and user economics','P/B equity reconciliation','DDM sensitivity','FCFE valuation','valuation replay','valuation mobile']:[]),...(process.env.GS_QA_EXPORTS==='1'?['XLSX download','PDF download','PPTX download']:[]),...(process.env.GS_QA_CALCULATIONS==='1'?['three calculation scenarios','replay verification','calculation mobile']:[]),...(process.env.GS_QA_TEMPLATES==='1'?['template upload','template sharing','template copy','template mobile']:[])],jsErrors:errors,externalRequests:external,mobileOverflow:overflow}));
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{await browser?.close();});

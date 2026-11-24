// Actual local UI capture. The caption layer is part of this recording, not the product.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawn}=require('node:child_process'),{once}=require('node:events');
const {createRequire}=require('node:module');
const req=createRequire(path.join(process.env.GS_NODE_MODULES,'playwright/package.json'));
const {chromium}=req('playwright');
const base=process.env.GS_APP_URL;
if(base!=='http://127.0.0.1:8081')throw Error('Demonstration must use the local pilot');
const build=path.resolve('.build-overview'),out=path.resolve('deliverables');
fs.mkdirSync(build,{recursive:true});fs.mkdirSync(out,{recursive:true});fs.mkdirSync('design/previews',{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let browser,encoder,recording=false,recordingLoop,recordStart,frameCount=0;
const chapters=[],errors=[];

(async()=>{
 browser=await chromium.launch({headless:true,channel:'chrome'});
 const context=await browser.newContext({viewport:{width:1600,height:1000},acceptDownloads:true});
 const page=await context.newPage();
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
 await page.goto(base+'/');
 await page.getByLabel('Login',{exact:true}).fill(process.env.GS_QA_LOGIN);
 await page.getByLabel('Password',{exact:true}).fill(process.env.GS_QA_PASSWORD);
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByRole('heading',{name:'Your watchlist',exact:true}).waitFor();
 const csrf=await page.locator('meta[name="csrf"]').getAttribute('content');
 const headers={'X-CSRF-Token':csrf,Origin:base};
 async function api(method,url,data){
  const r=await page.request.fetch(base+url,{method,headers:{...headers,'Idempotency-Key':crypto.randomUUID()},...(data?{data}:{})});
  if(!r.ok())throw Error(`${method} ${url}: ${r.status()} ${await r.text()}`);
  return r.json();
 }
 async function uploadDocument(name,bytes){
  const r=await page.request.post(base+'/api/v1/documents',{headers:{...headers,'Idempotency-Key':crypto.randomUUID()},multipart:{company_id:'jpm',file:{name,mimeType:'application/pdf',buffer:bytes}}});
  if(!r.ok())throw Error('Synthetic upload failed '+await r.text());
  const receipt=await r.json();
  await waitJob(receipt.job_id,'verify_original');await api('POST','/api/v1/jobs/'+receipt.job_id+'/extract');
  await waitJob(receipt.job_id,'extract_document');return receipt;
 }
 async function waitJob(id,kind){
  for(let i=0;i<90;i++){
   const r=await api('GET','/api/v1/jobs/'+id);
   if(r.state==='failed')throw Error('Synthetic job failed: '+r.error_code);
   if(r.state==='succeeded'&&r.kind===kind)return;
   await sleep(1000);
  }throw Error('Synthetic job timeout');
 }
 for(const id of ['jpm','hsbc','nu','sber','tinkoff'])await api('PUT','/api/v1/favorites/'+id);
 const doc=await uploadDocument('DEMO-financial-metrics.pdf',Buffer.from(process.env.GS_DEMO_PDF,'base64'));
 const ex=await api('GET','/api/v1/jobs/'+doc.job_id+'/extraction');
 const metrics=[['profit','100','Profit attributable to owners'],['equity','1,000','Total equity including NCI'],['assets','10,000','Total assets'],['roe','10%','ROE'],['roa','1%','ROA'],['nim','3.5%','NIM'],['cost_income','45%','Cost income ratio'],['npl','1.8%','NPL ratio'],['cost_risk','0.9%','Cost of risk']];
 const facts=[];
 for(const [metric,token,label] of metrics){
  const index=ex.items.findIndex(x=>(x.text||'').includes(label));const text=ex.items[index].text;
  const money=['profit','equity','assets'].includes(metric),instant=['equity','assets','npl'].includes(metric);
  const f=await api('POST','/api/v1/facts',{job_id:doc.job_id,item_index:index,number_text:token,source_start:text.indexOf(token,text.indexOf(label)),metric,unit:money?'money':'percent',scale:money?'millions':'units',currency:money?'USD':'',period_kind:instant?'instant':'year',period_start:instant?'':'2025-01-01',period_end:'2025-12-31',scope:'group',scope_detail:'Fictional demonstration consolidated group',accounting:'IFRS',definition:label,disclosure:'original'});
  facts.push(f);
  await api('POST',`/api/v1/facts/${f.id}/reviews`,{expected_revision:0,decision:'accepted',note:'Synthetic demonstration fixture only; not real analyst acceptance.'});
 }
 const review=await api('GET','/api/v1/review-state?company_id=jpm');
 const snapshot=await api('POST','/api/v1/input-snapshots',{company_id:'jpm',title:'DEMO: nine synthetic metrics',expected_state_hash:review.state_hash});
 const templateBytes=await(await page.request.get(base+'/api/v1/templates/demo')).body();
 const tr=await page.request.post(base+'/api/v1/templates',{headers:{...headers,'Idempotency-Key':crypto.randomUUID()},multipart:{title:'DEMO: five-year profit model',file:{name:'demo-template.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:templateBytes}}});
 if(!tr.ok())throw Error('Template fixture failed '+await tr.text());const template=await tr.json();
 const bind=value=>({value,note:'Synthetic demonstration assumption',confirmed:true});
 const scenarios={};for(const [name,growth] of [['base','0.05'],['optimistic','0.10'],['stress','0']])scenarios[name]={profit_owners:{fact_id:facts[0].id,note:'Synthetic parent-profit source in USD units',confirmed:true},growth:bind(growth)};
 const calc=await api('POST','/api/v1/calculations',{title:'DEMO: profit forecast',company_id:'jpm',template_id:template.template_id,version_id:template.id,snapshot_id:snapshot.id,scenarios,checks:[]});
 const vals={};
 for(const method of ['pe','pb','ddm','fcfe']){
  const assumptions={};for(const [name,multiple] of [['base','10'],['optimistic','12'],['stress','8']]){
   const values={shares:bind('10000000')};
   if(method==='pe')Object.assign(values,{profit_owners:{source_key:'profit_owners',note:'Synthetic source, linked calculation',confirmed:true},preferred_dividends:bind('0'),multiple:bind(multiple)});
   else if(method==='pb')Object.assign(values,{equity_total:bind('1000000000'),equity_nci:bind('0'),equity_preferred:bind('0'),multiple:bind(name==='base'?'1.0':name==='stress'?'0.8':'1.2')});
   else Object.assign(values,Object.fromEntries([1,2,3,4,5].map(i=>['cash_'+i,bind(name==='stress'?'70000000':name==='optimistic'?'110000000':'90000000')])),{cost_equity:bind('0.12'),terminal_growth:bind('0.02')});
   assumptions[name]=values;
  }
  vals[method]=await api('POST','/api/v1/valuations',{calculation_id:calc.id,title:'DEMO '+method.toUpperCase()+': fictional assumptions',method,currency:'USD',valuation_date:'2025-12-31',reference_year:2025,method_note:'Synthetic tour only. No issuer recommendation or methodology signoff.',scope_note:'Fictional consolidated common equity',shares_note:'Synthetic ordinary common shares',method_confirmed:true,capital_confirmed:true,comparability_confirmed:true,scenarios:assumptions});
 }
 console.log('Prepared synthetic documents, nine facts, snapshot, calculation and four valuations.');
 const section=await uploadDocument('DEMO-section-for-local-AI.pdf',Buffer.from(process.env.GS_DEMO_SECTION,'base64'));
 const sections=await api('GET','/api/v1/ai/batches/sections?job_id='+section.job_id);
 const chosen=sections.sections.find(x=>/income/i.test(x.title));if(!chosen)throw Error('No synthetic income section');
 const query=new URLSearchParams({job_id:section.job_id,section_id:chosen.id,with_context:'true',profile:'qwen_small'}).toString();
 const preview=await api('GET','/api/v1/ai/batches/preview?'+query);
 const batch=await api('POST','/api/v1/ai/batches',{job_id:section.job_id,section_id:chosen.id,with_context:true,profile:'qwen_small',page_start:preview.page_start,page_end:preview.page_end,plan_hash:preview.plan_hash});
 let batchState;
 for(let i=0;i<300;i++){
  batchState=await api('GET','/api/v1/ai/batches/'+batch.id);
  if(batchState.completed===batchState.total)break;
  // An explicit operator option applies only to this synthetic tour.
  if(batchState.state==='awaiting_device'&&process.env.GS_DEMO_CPU==='1'){
   await api('POST','/api/v1/ai/batches/'+batch.id+'/use-cpu');
   console.log('Explicit CPU selected for the synthetic demonstration.');
  }
  if(i%30===0)console.log('Demo AI batch: '+batchState.state);
  await sleep(1000);
 }
 if(!['succeeded','finished_with_gaps'].includes(batchState.state))throw Error('Demo AI batch still pending: '+batchState.state);
 let aiRun;
 for(const part of batchState.runs){const r=await api('GET','/api/v1/ai/runs/'+part.run_id);if(!aiRun||r.result?.proposals?.some(p=>p.metric==='profit'&&p.number_text==='120'))aiRun=r;}
 if(!aiRun)throw Error('Missing local AI receipt');
 const aiSucceeded=aiRun.result?.proposals?.some(p=>p.metric==='profit'&&p.number_text==='120');
 console.log('Actual AI outcome included honestly in the tour: '+aiRun.state);
 await require('./check_workbook_maps.cjs')(page,base);
 await page.setViewportSize({width:1600,height:1000});
 const maps=await api('GET','/api/v1/workbook-maps');const map=maps[0];
 // Show the annotation draft, without creating or approving any real gold labels.
 await page.goto(base+'/lab/new?job_id='+doc.job_id);
 await page.getByLabel('Workbook title',{exact:true}).fill('DEMO: annotation draft, not accepted gold');
 await page.getByRole('button',{name:'Prepare annotation workbook',exact:true}).click();
 await page.getByRole('link',{name:'Download annotation XLSX',exact:true}).waitFor();const labUrl=page.url();
 console.log('Prepared local AI result, workbook map and unapproved annotation draft. Recording starts.');

 const video=path.join(out,'GoldenStock-Project-Demo-2026-11-24.mp4');
 if(fs.existsSync(video))throw Error('Choose a new output filename instead of overwriting a video');
 encoder=spawn(process.env.GS_FFMPEG,['-hide_banner','-loglevel','error','-f','image2pipe','-framerate','8','-vcodec','mjpeg','-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',video],{stdio:['pipe','ignore','pipe']});
 const encodeErrors=[];encoder.stderr.on('data',x=>encodeErrors.push(x.toString()));
 recording=true;recordStart=Date.now();
 recordingLoop=(async()=>{
  while(recording){
   await sleep(Math.max(0,recordStart+frameCount*125-Date.now()));if(!recording)break;
   const frame=await page.screenshot({type:'jpeg',quality:82});
   do{if(!encoder.stdin.write(frame))await once(encoder.stdin,'drain');frameCount++;}while(frameCount*125<Date.now()-recordStart-125);
  }
 })();
 async function caption(title,body){
  chapters.push({title,body,start:Number(((Date.now()-recordStart)/1000).toFixed(2))});
  await page.evaluate(({title,body})=>{
   document.getElementById('gs-demo-caption')?.remove();
   const box=document.createElement('aside');box.id='gs-demo-caption';
   box.style.cssText='position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:rgba(18,44,35,.97);color:white;padding:15px 34px 18px;font:20px/1.35 Arial,sans-serif;border-top:3px solid #c8a660;pointer-events:none';
   const h=document.createElement('strong');h.textContent=title;h.style.cssText='display:block;font-size:24px;margin-bottom:5px;color:#e7d3a4';
   const p=document.createElement('div');p.textContent=body;
   const tag=document.createElement('small');tag.textContent='ДЕМОНСТРАЦИЯ: все финансовые значения синтетические. Это не оценка эмитента.';tag.style.cssText='display:block;font-size:14px;margin-top:8px;color:#cbd9d0';
   box.append(h,p,tag);document.body.append(box);
  },{title,body});
 }
 async function scene(slug,url,title,body,hold=13,focus){
  const response=await page.goto(url.startsWith('http')?url:base+url,{waitUntil:'networkidle'});
  if(!response?.ok())throw Error('Demo page did not load: '+slug);
  if(focus)await focus();
  await page.screenshot({path:'design/previews/overview-'+slug+'.png'});
  await caption(title,body);await sleep(hold*1000);
  console.log('Recorded chapter: '+slug);
 }
 await scene('watchlist','/','01. Рабочее место аналитика','Это запись локального GoldenStock. Для тура подготовлен отдельный кабинет с учебными документами и моделями. В избранном пять компаний.',17);
 await scene('company','/company/jpm','02. Карточка компании','Аналитик открывает компанию, переходит к источникам, файлам, проверке данных и личной оценке. Учебная модель не является реальной оценкой JPMorgan.',15);
 await scene('sources','/sources?company_id=jpm','03. Доверенные источники','В пилоте используются официальные раскрытия и SEC. Английские пробелы по российским эмитентам сохраняются явно.',14);
 await scene('files','/files?company_id=jpm','04. Личные оригиналы','Здесь два учебных PDF: девять финансовых метрик и раздел для локального ИИ. Оригиналы сохраняются отдельно от результатов обработки.',16);
 await scene('extraction','/extraction/'+doc.job_id,'05. Извлечённые данные','PDF, OCR, XLSX и PPTX превращаются в исходные фрагменты с координатами. Число остаётся связано со страницей или ячейкой документа.',15);
 await scene('sections','/ai-sections?job_id='+section.job_id,'06. Выбор раздела по названию','Вместо ручного перебора страниц аналитик выбирает заголовок отчёта. Предполагаемый диапазон можно проверить перед запуском.',14);
 await scene('preview','/ai-batch-preview?'+query,'07. Точный вход локального ИИ','Основные фрагменты и соседний контекст показаны отдельно. Браузер отправляет задачу серверу, а не обращается к модели напрямую.',15);
 await scene('batch','/ai-batch/'+batch.id,'08. Пакетная обработка','У пакета есть общий прогресс, отдельные части, отмена и повтор ошибок. Результат этого учебного раздела получен установленным локальным Qwen.',14);
 await scene('ai-result','/ai-run/'+aiRun.id,aiSucceeded?'09. Число, контекст и источник':'09. Неподтверждённый ответ отклонён',aiSucceeded?'Предложение содержит число и контекст. Оно остаётся непроверенным до решения аналитика.':'В этой попытке малый Qwen на CPU не прошёл проверку источника. Сервер отклонил ответ. Такой результат не попадает в расчёт как подтверждённый факт.',20,aiSucceeded?async()=>page.getByRole('heading',{name:'profit: 120',exact:true}).scrollIntoViewIfNeeded():undefined);
 await scene('normalize','/normalize/'+doc.job_id+'/0','10. Нормализация факта','Аналитик выбирает точное число и задаёт единицу, масштаб, период, периметр и определение. Миллионы и проценты не смешиваются.',16);
 await scene('review','/review/jpm','11. Проверка и снимок входов','Для тура подготовлены девять проверенных учебных метрик. В реальной работе все включённые факты подтверждает аналитик. Решения сохраняются с историей.',19);
 await scene('snapshot','/review/jpm','12. Зафиксированный набор данных','Снимок связывает расчёт с конкретными фактами и решениями. Изменение проверки не переписывает прежнюю оценку.',15,async()=>page.getByRole('heading',{name:'Verified input sets',exact:true}).scrollIntoViewIfNeeded());
 await scene('templates','/templates/'+template.template_id,'13. Excel-шаблон','Сохраняются оригинальная книга, версия и очищенная структура. Личная исходная книга остаётся у автора.',14);
 await caption('14. Публикация общей структуры','Автор явно публикует очищенный шаблон внутри фонда. Личные исходные значения и рассчитанные оценки не становятся общими.');
 await page.getByRole('button',{name:'Share clean structure with fund',exact:true}).click();await page.getByRole('button',{name:'Make private',exact:true}).waitFor();
 await caption('14. Публикация общей структуры','Версия опубликована. Каждый активный сотрудник с доступом получает собственное уведомление об этой версии.');await sleep(14000);
 await scene('template-updates','/updates?category=models','15. Уведомление о новой версии','В одной записи видны изменения общей версии. Повтор публикации не создаёт дубликаты уведомлений.',15);
 await scene('workbook-map','/workbook-maps/'+map.id,'16. Карта обычной Excel-книги','Мастер связывает ячейки с девятью банковскими метриками и собственными полями. Подтверждения относятся к конкретной версии карты.',19,async()=>page.getByRole('heading',{name:'Mapping review',exact:true}).scrollIntoViewIfNeeded());
 await scene('calculation','/calculations/'+calc.id,'17. Воспроизводимый расчёт','Детерминированный движок Decimal рассчитывает базовый, оптимистичный и стрессовый сценарии. ИИ не выполняет финансовую арифметику.',17);
 await page.getByRole('button',{name:'Verify reproducibility',exact:true}).click();await page.getByRole('status').filter({hasText:'Replay matched'}).waitFor();
 await caption('18. Проверка воспроизводимости','Повтор по сохранённым входам совпал с исходным результатом. Это проверка расчёта, а не подтверждение инвестиционной гипотезы.');await sleep(12000);
 await scene('valuation','/valuations/'+vals.pe.id,'19. Сценарный диапазон стоимости','Учебная оценка P/E показывает 80–120 USD за акцию и 0,8–1,2 млрд USD стоимости капитала. Это результат синтетических предпосылок.',20);
 await scene('ddm','/valuations/'+vals.ddm.id,'20. Отдельные методы оценки','DDM и FCFE используют денежные потоки к акционерам. P/E и P/B используют разные базы. Приложение не смешивает методы в один необъяснимый диапазон.',18);
 await page.goto(base+'/valuations/'+vals.pe.id);await page.getByRole('heading',{name:'Download this valuation',exact:true}).scrollIntoViewIfNeeded();
 await caption('21. Экспорт результата','Из одного сохранённого снимка формируются XLSX, PDF и PPTX. В экспортах сохраняются предпосылки, источники и исторический статус проверки.');
 for(const kind of ['xlsx','pdf','pptx']){
  const href=`/api/v1/valuations/${vals.pe.id}/export/${kind}`;const link=page.locator(`a[href="${href}"]`);
  const [download]=await Promise.all([page.waitForEvent('download'),link.click()]);await download.saveAs(path.join(build,'demo-export.'+kind));await sleep(3000);
 }await sleep(7000);
 await scene('lab','/lab','22. AI Lab','Отдельный кабинет хранит версии эталонов и сравнивает локальные профили на одинаковых входах. Числовые метрики и проверка контекста показаны раздельно.',16);
 await scene('lab-workbook',labUrl,'23. Таблица ручной разметки','Этот XLSX остаётся черновиком. Импорт требует предпросмотра изменений и явного подтверждения. Реальные gold-факты в этом туре не создавались.',18);
 await scene('team','/team','24. Команда и доступ','Организация, сотрудники и отзыв сессий контролируются сервером. В записи используется отдельный демонстрационный аккаунт, который будет отозван.',15);
 await scene('final','/','25. Статус пилота','32 из 36 задач завершены технически. Реальное качество 95%, обновление за десять минут, методическая и полевая приёмка ещё открыты.',20);
 recording=false;await recordingLoop;encoder.stdin.end();
 const [code]=await once(encoder,'close');if(code)throw Error('Video encode failed: '+encodeErrors.join('').slice(-2000));
 const duration=frameCount/8;
 fs.writeFileSync(path.join(build,'demo-chapters.json'),JSON.stringify({duration,chapters,errors,synthetic:true,aiState:aiRun.state,aiError:aiRun.error,scope:'Actual local UI, prepared synthetic data, no real acceptance'},null,2));
 if(errors.length)throw Error('Browser errors in demonstration: '+errors.join('; '));
 console.log(JSON.stringify({video,duration,chapters:chapters.length,frames:frameCount,synthetic:true,jsErrors:errors}));
})().catch(e=>{console.error(e.message);process.exitCode=1;}).finally(async()=>{
 recording=false;if(recordingLoop)await recordingLoop.catch(()=>{});if(encoder&&!encoder.killed)encoder.stdin.end();
 if(browser)await browser.close();
});

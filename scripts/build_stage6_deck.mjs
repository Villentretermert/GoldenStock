// Local review, using the established GoldenStock palette. No uploads.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd(), home=process.env.USERPROFILE;
const runtime=path.join(home,'.cache/codex-runtimes/codex-primary-runtime/dependencies');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const skill=path.join(home,'.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations');
const {Presentation,PresentationFile}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')));
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')));
const build=path.join(root,'.build-stage6-deck'), output=path.join(root,'deliverables');
await fs.mkdir(build,{recursive:true});await fs.mkdir(output,{recursive:true});
const p=Presentation.create({slideSize:{width:1280,height:720}});
const green='#193B30', amber='#88641D', muted='#627367';
function text(s,t,x,y,w,h,size=27,color=green,bold=false){
 const b=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 b.text=t;b.text.style={typeface:'Arial',fontSize:size,color,bold};return b;
}
function slide(title,source){const s=p.slides.add();s.background.fill='#F5F5EF';if(title)text(s,title,64,43,1152,90,39,green,true);s.speakerNotes.text='Источники и границы доказательств: '+source;return s;}
function line(s,x,y,w,color='#C8D4CB'){s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:2},fill:color,line:{fill:'none',width:0}});}
function box(s,t,x,y,w,h,pending=false){s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:pending?'#F0E7D5':'#E2EDE5',line:{fill:pending?amber:green,width:1}});text(s,t,x+16,y+15,w-32,h-20,23,pending?amber:green,true);}
async function screen(s,name,x,y,w,h){s.images.add({blob:new Uint8Array(await fs.readFile(path.join(root,'design/previews',name))),contentType:'image/png',position:{left:x,top:y,width:w,height:h},fit:'contain'});}

let s=slide('', 'docs/STAGE_6_REVIEW.md; docs/PILOT_ACCEPTANCE.md. Дата 3 ноября 2026.');
text(s,'GoldenStock\nПодготовка к пилоту фонда',64,140,1152,200,57,green,true);
text(s,'Обзор GS-021–024\n3 ноября 2026',64,405,1152,100,31);
line(s,64,560,1152);
text(s,'Технический сценарий проверен.\nДопуск фонда ожидает реального UAT и полевых проверок.',64,586,1152,90,28,amber);

s=slide('Результаты завершающего этапа','docs/AI_LAB.md; docs/MONITORING.md; docs/PILOT_OPERATIONS.md; docs/PILOT_ACCEPTANCE.md.');
text(s,'GS-021   AI Lab',64,155,285,50,30,green,true);text(s,'Два локальных профиля, слепая разметка, версии и holdout',365,155,850,65,28);
line(s,64,237,1152);
text(s,'GS-022   Updates',64,267,285,50,30,green,true);text(s,'SEC по избранному, личные события, дедупликация и recovery',365,267,850,70,28);
line(s,64,353,1152);
text(s,'GS-023   REVIEW',64,383,285,50,30,amber,true);text(s,'Tailscale подготовлен. Зашифрованное восстановление проверено',365,383,850,75,28);
line(s,64,470,1152);
text(s,'GS-024   REVIEW',64,501,285,50,30,amber,true);text(s,'Сквозной тест, условия допуска, обучение и годовой план',365,501,850,75,28);
text(s,'Реальная accuracy 95% и приёмка фондом остаются открытыми.',64,635,1152,50,25,amber);

s=slide('AI Lab сохраняет сравнимые эксперименты','docs/AI_LAB.md; design/previews/lab-proposals-desktop.png, синтетическая проверка GS-021.');
await screen(s,'lab-proposals-desktop.png',40,135,810,540);
text(s,'1. Зафиксировать источник\nи эталон до генерации\n\n2. Запустить два профиля\nчерез общую GPU-очередь\n\n3. Разметить варианты\nи раскрыть модели',865,160,350,390,25);
text(s,'Скриншот синтетический.\nРеальные эталоны ещё\nдолжен проверить аналитик.',865,580,350,100,22,amber);

s=slide('Новые раскрытия появляются в Updates','docs/MONITORING.md; design/previews/monitor-feed.png, синтетическое событие; шесть SEC endpoints проверены 1 ноября 2026.');
await screen(s,'monitor-feed.png',40,135,810,540);
text(s,'Проверка каждые 6 часов\nпо избранным компаниям\n\nBaseline, новые события,\nошибки и восстановление\n\nСохранённые оценки\nаналитик пересчитывает сам',865,160,350,390,25);
text(s,'JPMorgan, HSBC и Nu\nимеют SEC-коннекторы.\nПо Сберу и Т — пробелы.',865,580,350,100,22,amber);

s=slide('Система и границы готовности','docs/ARCHITECTURE.md; docs/AI_LAB.md; docs/MONITORING.md; docs/PILOT_OPERATIONS.md. Зелёный — реализовано, охра — полевая приёмка.');
box(s,'Браузер\nPython UI',64,160,240,95);box(s,'FastAPI\nSession / ACL',370,160,240,95);box(s,'PostgreSQL\nВерсии и аудит',680,160,260,95);
line(s,304,207,66,green);line(s,610,207,70,green);
box(s,'Worker\nParser / очередь',64,335,240,100);box(s,'OllamaProvider\nЛокальный Qwen',370,335,280,100);box(s,'Monitor\nОфициальный SEC',730,335,310,100);
line(s,304,382,66,green);
text(s,'Файлы и шаблоны в локальном FileStore.\nИИ получает задания от worker, браузер обращается к API.',64,473,1152,85,26);
box(s,'Tailscale фонда\nВторое устройство',64,590,335,95,true);box(s,'Отдельный backup\nРасписание / cold boot',440,590,350,95,true);box(s,'Реальная разметка\nПодписание UAT',830,590,385,95,true);

s=slide('Код фиксирует версии, решения и происхождение','src/goldenstock/ai_lab.py; src/goldenstock/monitoring.py; ops/recovery.py; evaluation/acceptance.py.');
text(s,'LabDataset / LabExperiment / LabAnnotation',64,155,1152,50,29,green,true);
text(s,'Неизменяемые входы, digest модели, слепые ревизии решений',64,212,1152,60,27);
text(s,'MonitorSnapshot / MonitorEvent / SiteNotification',64,305,1152,50,29,green,true);
text(s,'Снимок SEC, семантическое сравнение, доставка владельцу',64,362,1152,60,27);
text(s,'recovery.py / acceptance.py',64,455,1152,50,29,green,true);
text(s,'Общая точка БД и файлов, SHA-256, restore на чистом стенде.\nПроверка 11 критериев допуска возвращает GO / NO-GO / INVALID.',64,513,1152,105,27);
text(s,'Новые тесты используют HTTP API и настоящий parser subprocess.',64,650,1152,40,23,muted);

s=slide('Проверки дают технические доказательства','3 ноября: pytest 246 passed / 1 skipped, scripts/check_browser.py 31 сценарий. 2 ноября: check_recovery.py 32 таблицы, 3 файла, 15 HTTPS accounts, p50/p95 437/467 ms. CI GS-023 https://github.com/Villentretermert/GoldenStock/actions/runs/41436367753');
text(s,'246',64,160,300,100,75,green,true);text(s,'тестов прошли\nOCR отдельно в Docker',64,280,320,100,25);
text(s,'5',470,160,300,100,75,green,true);text(s,'компаний в сквозном тесте\nСинтетические документы',470,280,350,100,25);
text(s,'31',900,160,300,100,75,green,true);text(s,'браузерный сценарий\nDesktop и mobile',900,280,315,100,25);
line(s,64,416,1152);
text(s,'Репетиция GS-023 восстановила 32 таблицы и три файла.\n15 HTTPS-сессий прошли проверку входа и чтения.\nХеши файлов, старые сессии и отзыв доступа проверены.',64,460,1152,150,29);
text(s,'Это не измерение качества реальных отчётов или нагрузки 45 документов/день.',64,641,1152,50,23,amber);

s=slide('Допуск фонда сейчас имеет статус NO-GO','docs/PILOT_ACCEPTANCE.md; evaluation/acceptance.py. Все открытые пункты остаются блокерами выпуска для фонда.');
text(s,'Реальные факты и методика',64,160,525,55,30,green,true);
text(s,'Один аналитик, до 8 часов в неделю\nТри реальные модели зарубежных компаний\nСлепой эталон и измеренная accuracy\nОткрытие XLSX/PDF/PPTX в Office',64,243,525,235,27);
text(s,'Полевая эксплуатация',690,160,525,55,30,green,true);
text(s,'Tailscale и второе устройство\nОтдельный носитель и расписание\nПерезапуск Windows и WSL\n45 документов/день при другой GPU-нагрузке',690,243,525,235,27);
line(s,64,525,1152);
text(s,'Проверяющий скрипт оценивает предоставленный протокол.\nОператор и фонд подписывают допуск конкретной версии приложения.',64,568,1152,110,28,amber);

s=slide('Год пилота начинается после приёмки','docs/PILOT_YEAR_PLAN.md. Срок от допуска — рабочее допущение, календарная дата не назначена.');
text(s,'Месяцы 1–3',64,160,280,55,31,green,true);text(s,'Обучение 2–3 аналитиков, затем до 15.\nИзмерение времени работы и частоты исправлений.',380,160,835,105,29);
line(s,64,282,1152);
text(s,'Месяцы 4–6',64,315,280,55,31,green,true);text(s,'Цикл отчётности, шаблоны, повторная приёмка\nи восстановление реальной резервной копии.',380,315,835,105,29);
line(s,64,437,1152);
text(s,'Месяцы 7–12',64,470,280,55,31,green,true);text(s,'Сравнение локального ИИ, объём данных и расходы.\nИтоговое решение о следующей версии или облаке.',380,470,835,105,29);
text(s,'До старта нужны назначенные роли и закрытые P0 из протокола UAT.',64,638,1152,50,25,amber);

s=slide('Следующий шаг зависит от ответов фонда','docs/STAGE_6_REVIEW.md, 12 вопросов контрольной точки. Инструкции docs/ANALYST_QUICKSTART.md и docs/PILOT_ACCEPTANCE.md.');
text(s,'Сначала реальный эталон и модель JPMorgan.\nЗатем HSBC и Nu, проверка экспортов и замечаний.\nПосле этого полевой доступ, backup и рабочая нагрузка.',64,170,1152,220,32);
text(s,'Так аналитик проверит полезность и методику до подключения всех коллег.\nTailscale фонда и отдельный носитель подключаются в согласованный срок.',64,445,1152,120,28);
line(s,64,596,1152);
text(s,'Контрольная точка завершает обзор этапа.\n12 вопросов сохранены в STAGE_6_REVIEW.md.',64,620,1152,75,25,amber);

for(let i=0;i<p.slides.items.length;i++){
 const blob=await p.export({slide:p.slides.getItem(i),format:'png',scale:1});
 await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));
}
const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:path.join(output,'GoldenStock-Stage-6-final.pptx'),pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],fontPolicy:{basis:'design',families:['Arial']},requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],verifyArtifactToolImport:true,receiptPath:path.join(build,'validation-final.json')});
console.log(JSON.stringify(result));

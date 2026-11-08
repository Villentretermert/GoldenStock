// Local checkpoint presentation. Real documents and screenshots stay outside Git.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd(), home=process.env.USERPROFILE;
const runtime=path.join(home,'.cache/codex-runtimes/codex-primary-runtime/dependencies');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const skill=path.join(home,'.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations');
const {Presentation,PresentationFile,FileBlob}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')));
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')));
const build=path.join(root,'.build-stage8-deck-final'), output=path.join(root,'deliverables');
await fs.mkdir(build,{recursive:true});await fs.mkdir(output,{recursive:true});
const p=Presentation.create({slideSize:{width:1280,height:720}});
const green='#193B30', amber='#88641D', muted='#627367', bg='#F5F5EF';
function text(s,t,x,y,w,h,size=28,color=green,bold=false){
 const b=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 b.text=t;b.text.style={typeface:'Arial',fontSize:size,color,bold};return b;
}
function slide(title,source){const s=p.slides.add();s.background.fill=bg;if(title)text(s,title,64,44,1152,95,40,green,true);s.speakerNotes.text=source;return s;}
function line(s,x,y,w,color='#C8D4CB'){s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:2},fill:color,line:{fill:'none',width:0}});}
function node(s,t,x,y,w,h,pending=false){s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:pending?'#F0E7D5':'#E2EDE5',line:{fill:pending?amber:green,width:1}});text(s,t,x+14,y+14,w-28,h-20,24,pending?amber:green,true);}
function table(s,values,widths,y=170,h=335){
 const tb=s.tables.add({rows:values.length,columns:values[0].length,left:64,top:y,width:1152,height:h,columnWidths:widths,values});
 tb.borders.assign({fill:'#C8D4CB',width:1,style:'solid'});
 for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){
  const cell=tb.getCell(r,c);cell.fill=r===0?green:bg;
  cell.text.style={typeface:'Arial',fontSize:25,color:r===0?'#FFFFFF':green,bold:r===0};
 }
 return tb;
}
async function screen(s,name,x,y,w,h){s.images.add({blob:new Uint8Array(await fs.readFile(path.join(root,'design/previews',name))),contentType:'image/png',position:{left:x,top:y,width:w,height:h},fit:'contain'});}

let s=slide('','8 ноября 2026. docs/PROJECT_PLAN.md; docs/STAGE_8_REVIEW.md.');
text(s,'GoldenStock\nОт раздела отчёта к эталону',64,150,1152,200,58,green,true);
text(s,'Обзор GS-029–032\n8 ноября 2026',64,405,1152,100,31);
text(s,'28 из 36 задач завершены в техническом объёме.\nЧетыре задачи разработки и четыре задачи приёмки остаются открытыми.',64,575,1152,100,29,amber);

s=slide('Четыре завершённые задачи','docs/AI_BATCHES.md; REPORT_SECTIONS.md; AI_RESOURCES.md; LAB_EXCHANGE.md.');
table(s,[['Задача','Изменение','Практический результат'],['GS-029','Пакет PDF-страниц','Общий прогресс, отмена и повтор'],['GS-030','Выбор раздела по названию','Контекст с отдельными ссылками'],['GS-031','Контроль GPU и явный CPU','Выбор устройства и история попыток'],['GS-032','Разметка через XLSX','Сравнение изменений и новая версия']],[165,440,547],160,400);
text(s,'Цель следующего замера: обновить готовую модель по девяти метрикам\nдо проверенного экспорта за десять минут.',64,610,1152,80,28,amber);

s=slide('Пакет начинается с выбора раздела','docs/REPORT_SECTIONS.md; design/previews/report-sections.png. Синтетический пример реального кабинета.');
await screen(s,'report-sections.png',40,145,780,540);
text(s,'Заголовки помогают найти\nнужные страницы отчёта.\n\nАналитик проверяет границы\nи запускает пакет.\n\nСоседний текст передаётся\nс собственными источниками.',855,170,355,350,27);
text(s,'Qwen может оставить\nвалюту, масштаб и период\nпустыми. Проверка обязательна.',855,570,355,110,25,amber);

s=slide('Недостаток GPU требует явного выбора','docs/AI_RESOURCES.md; design/previews/ai-device-choice.png. Экран создан синтетической проверкой нехватки ресурсов. Реальный CPU отдельно проверен в GS-031.');
await screen(s,'ai-device-choice.png',40,145,780,540);
text(s,'Проверка резерва 3 GiB VRAM\nперед каждой загрузкой.\n\nПри нехватке памяти — CPU\nили повторная проверка GPU.\n\nИстория хранит устройство\nи время каждой попытки.',855,170,355,390,27);
text(s,'Жёсткая изоляция VRAM\nдругих программ отсутствует.',855,600,355,85,24,amber);

s=slide('Excel возвращается через проверку изменений','docs/LAB_EXCHANGE.md; design/previews/lab-import-desktop.png. Синтетические данные, не разметка JPMorgan.');
await screen(s,'lab-import-desktop.png',40,145,780,540);
text(s,'В книге четыре листа:\nLabels, Cases, Sources, Guide.\n\nСначала показываются\nпрежние и новые значения.\n\nНовая версия эталона\nсохраняется после отметки\nи пояснения аналитика.',855,170,355,380,27);
text(s,'Черновик и предпросмотр\nне считаются принятыми\nэталонными фактами.',855,590,355,95,25,amber);

s=slide('Системный дизайн и статусы','src/goldenstock/ai_batches.py; report_sections.py; ai_resources.py; lab_exchange.py. Зелёный — технически реализовано; охра — ожидает реальной приёмки.');
node(s,'Браузер\nPython UI',64,155,250,100);node(s,'FastAPI / ACL\nИсточники и версии',390,155,300,100);node(s,'PostgreSQL\nФайлы и журнал',770,155,400,100);
line(s,314,205,76,green);line(s,690,205,80,green);
node(s,'Раздел / AIBatch\nТекст и контекст',64,320,300,105);node(s,'Worker / DeviceGuard\nОбщая очередь',430,320,330,105);node(s,'Адаптер / Qwen\nЛокальный ИИ',825,320,345,105);
line(s,364,372,66,green);line(s,760,372,65,green);
text(s,'Разметка: LabExchange → LabImport → подтверждение → LabDataset.\nРасчёт: подтверждённые факты → снимок → оценка → экспорт.',64,475,1152,95,27);
node(s,'Реальные эталоны\nGS-004',64,600,340,85,true);node(s,'Полевая эксплуатация\nGS-023',445,600,345,85,true);node(s,'Методика и допуск\nGS-001 / GS-024',830,600,380,85,true);

s=slide('Компоненты кода и сохраняемые сущности','src/goldenstock/models.py; ai_batches.py; report_sections.py; ai_resources.py; lab_exchange.py; lab_workbook.py. Миграции 0017–0019.');
table(s,[['Компонент','Что сохраняется'],['ai_batches / AIBatch','Страницы, план, входы, прогресс и попытки'],['report_sections / context','Заголовок, границы и отдельные локаторы'],['ai_resources / AIExecution','Устройство, измерения, время и причина остановки'],['lab_exchange / LabExchange','Личные источники, версия и разделение набора'],['lab_workbook / LabImport','Оригинал XLSX, изменения и подтверждение']],[435,717],155,430);
text(s,'LabDataset остаётся неизменяемым. Проверочные данные хранятся вне весов\nи применяются к другой локальной модели через AI Lab.',64,615,1152,80,27);

s=slide('Проверки подтверждают технический результат','docs/LAB_EXCHANGE.md; scripts/check_postgres.py; check_browser.py; check_recovery.py. Локальный полный прогон 329 passed / 1 skipped; окончательный затронутый набор 24 passed.');
text(s,'329',64,165,310,95,72,green,true);text(s,'тестов полного набора\nОдин OCR пропущен в Windows',64,280,350,95,26);
text(s,'24',475,165,310,95,72,green,true);text(s,'финальных проверки XLSX\nВсе прошли',475,280,350,95,26);
text(s,'37',900,165,310,95,72,green,true);text(s,'таблиц восстановлено\nОригинал импорта сохранён',900,280,315,95,26);
line(s,64,420,1152);
text(s,'Chrome: импорт, подтверждение, мобильный экран и прежние сценарии.\nPostgreSQL: одновременные запросы без дублей. Linux OCR прошёл.\nВосстановление: четыре файла, 15 HTTPS-сессий и прежняя история ИИ.',64,465,1152,150,28);
text(s,'Синтетические проверки не подтверждают качество реальной финансовой модели.',64,650,1152,40,24,amber);

s=slide('Восемь задач остаются открытыми','docs/PROJECT_PLAN.md; ISSUER_CORPUS.md; PILOT_ACCEPTANCE.md; STAGE_7_ANSWERS.md.');
text(s,'Четыре задачи разработки',64,165,535,50,32,green,true);
text(s,'GS-033 — сравнение данных SEC\nGS-034 — уведомления читателям\nGS-035 — диапазон стоимости первым\nGS-036 — мастер Excel-книги',64,250,545,240,28);
text(s,'Четыре задачи приёмки',690,165,525,50,32,green,true);
text(s,'GS-001 — приёмка продукта\nGS-004 — ручные эталоны и 95%\nGS-023 — сеть, носитель, перезапуск\nGS-024 — методика и реальный UAT',690,250,525,240,28);
text(s,'Реальных принятых gold-фактов: 0. Обновление за десять минут не измерено.\nПроверка JPMorgan, сеть фонда и носитель остаются отложенными вами.',64,565,1152,110,28,amber);

s=slide('Следующий этап уточняет обновление модели','docs/STAGE_8_REVIEW.md; PROJECT_RULES.md, пункты 6–7. Вопросы задаются после презентации; GS-033 до ответов не начинается.');
text(s,'После ответов — GS-033, затем GS-034–036.',64,165,1152,70,38,green,true);
text(s,'Сравнение SEC покажет, какие значения изменились.\nУведомления доведут обновление общей модели до её читателей.\nДиапазон сценариев упростит просмотр оценки.\nМастер Excel позволит подключать пользовательские книги.',64,290,1152,225,31);
text(s,'12 вопросов контрольной точки сохранены в текстовом обзоре.\nСледующая задача начнётся после ответов или явного поручения\nсамостоятельно выбрать настройки.',64,580,1152,105,27,amber);

const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
const finalPath=path.join(output,'GoldenStock-Stage-8-2026-11-08.pptx');
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','2','--require-native-table-slide','7'],fontPolicy:{basis:'design',families:['Arial']},requiredNativeTableOwnerSlides:[2,7],requiredNativeChartOwnerSlides:[],verifyArtifactToolImport:true,receiptPath:path.join(build,'validation-delivery.json')});
const imported=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(let i=0;i<imported.slides.items.length;i++){
 const blob=await imported.export({slide:imported.slides.getItem(i),format:'png',scale:1});
 await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));
}
console.log(JSON.stringify(result));


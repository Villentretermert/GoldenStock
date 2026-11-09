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
const build=path.join(root,'.build-stage9-deck-reviewed'), output=path.join(root,'deliverables');
await fs.mkdir(build,{recursive:true});await fs.mkdir(output,{recursive:true});
const p=Presentation.create({slideSize:{width:1280,height:720}});
const green='#193B30', amber='#88641D', muted='#627367', bg='#F5F5EF';
function text(s,t,x,y,w,h,size=28,color=green,bold=false){
 const b=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 b.text=t;b.text.style={typeface:'Arial',fontSize:size,color,bold};return b;
}
function slide(title,source){const s=p.slides.add();s.background.fill=bg;if(title)text(s,title,64,44,1152,95,44,green,true);s.speakerNotes.text=source;return s;}
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

let s=slide('','9 ноября 2026. docs/PROJECT_PLAN.md; docs/STAGE_9_REVIEW.md.');
text(s,'GoldenStock\nОбновление финансовой модели',64,160,1152,205,58,green,true);
text(s,'Обзор GS-033–036\n9 ноября 2026',64,430,1152,100,31);
text(s,'32 из 36 задач завершены в техническом объёме.\nЧетыре задачи реальной приёмки остаются открытыми.',64,585,1152,90,29,amber);

s=slide('Результаты четырёх задач','docs/SEC_COMPARISON.md; TEMPLATE_PUBLICATIONS.md; SCENARIO_RANGES.md; WORKBOOK_MAPPING.md.');
table(s,[['Задача','Изменение','Результат для аналитика'],['GS-033','Сравнение и история SEC','Прежнее значение и причина обновления'],['GS-034','Публикации Excel-версий','Одно уведомление каждому читателю'],['GS-035','Сценарный диапазон первым','Цена акции и стоимость капитала'],['GS-036','Мастер Excel-книги','Карта ячеек и проверяемый расчёт']],[150,440,562],165,410);
text(s,'Цель пилота — обновление готовой модели по девяти метрикам\nдо проверенного экспорта за десять минут. Замер ещё предстоит.',64,605,1152,80,28,amber);

s=slide('Изменения данных SEC','docs/SEC_COMPARISON.md; design/previews/sec-comparison-desktop.png. Синтетическая проверка интерфейса.');
await screen(s,'sec-comparison-desktop.png',40,145,790,540);
text(s,'Пересмотры и новые\nпериоды — отдельно.\n\nПрежнее значение\nи история источника.\n\nИзменения от 5%\nвыделены.',865,180,350,365,26);
text(s,'Первое покрытие: прибыль,\nкапитал и активы.\nФакты не утверждаются\nавтоматически.',865,560,350,120,25,amber);

s=slide('Публикация общей Excel-версии','docs/TEMPLATE_PUBLICATIONS.md; design/previews/publication-preview-desktop.png. Синтетический шаблон.');
await screen(s,'publication-preview-desktop.png',40,145,790,540);
text(s,'Автор видит список изменений\nдо публикации.\n\nКаждый активный сотрудник\nполучает личное уведомление.\n\nПовтор публикации версии\nне создаёт дубль.',865,180,350,340,26);
text(s,'Общая структура содержит\nпустые входы. Личный\nисходник и расчёты\nне передаются коллегам.',865,555,350,125,25,amber);

s=slide('Сценарный диапазон оценки','docs/SCENARIO_RANGES.md; design/previews/valuation-range-desktop.png. Синтетический пример P/E; не оценка публичной компании.');
await screen(s,'valuation-range-desktop.png',40,145,790,540);
text(s,'Цена акции и общая стоимость\nобыкновенного капитала.\n\nБазовая точка и сценарии,\nзадающие минимум и максимум.\n\nDDM, FCFE, P/E и P/B\nпоказываются раздельно.',865,180,350,365,26);
text(s,'Сохранённый расчёт\nне меняется. Статус\nпроверки источников\nпоказан рядом.',865,560,350,115,25,amber);

s=slide('Карта обычной Excel-книги','docs/WORKBOOK_MAPPING.md; design/previews/workbook-map-desktop.png. Синтетическая книга, не финансовая модель JPMorgan.');
await screen(s,'workbook-map-desktop.png',40,145,790,540);
text(s,'Девять банковских метрик\nи собственные поля.\n\n120 млн USD →\n120 000 000 USD\n2,5% → 0,025.\n\nИзменения карты требуют\nнового подтверждения.',865,175,350,380,26);
text(s,'SUM/IF и другие функции\nпока требуют исключения\nили ручного ввода\nс пояснением.',865,560,350,120,25,amber);

s=slide('Системный дизайн и границы готовности','src/goldenstock/api.py; models.py; workbook_mapping.py; workbook_maps.py; calculations.py; docs/PILOT_ACCEPTANCE.md. Сплошные связи — реализованные пути; нижний ряд — открытая приёмка.');
node(s,'Python Web UI\nКабинет аналитика',64,160,320,100);
node(s,'API / ACL / CSRF\nКонтроль версий',480,160,320,100);
node(s,'PostgreSQL 0022\nОригиналы файлов',896,160,320,100);
text(s,'→',410,180,45,50,34);text(s,'→',826,180,45,50,34);
node(s,'SEC monitor\nИстория и уведомления',64,330,320,120);
node(s,'Карты → шаблоны\nDecimal → оценка → экспорт',480,330,320,120);
node(s,'Очередь → local AI\nПредложения и Review',896,330,320,120);
text(s,'↑',202,270,45,50,34);text(s,'↓',618,270,45,50,34);text(s,'↓',1034,270,45,50,34);
node(s,'Открыто: реальные gold,\n95%, методика, 10 минут',64,540,545,105,true);
node(s,'Открыто: сеть фонда,\nвнешний носитель, перезапуск',671,540,545,105,true);
text(s,'ИИ вызывается только сервером. Карты и расчёты не зависят от весов модели.',64,665,1152,35,24);

s=slide('Компоненты и сущности','src/goldenstock/monitor_history.py; template_publications.py; valuation_summary.py; workbook_mapping.py; workbook_maps.py; models.py.');
table(s,[['Компонент','Сущность / ответственность'],['monitor_history','MonitorFactVersion — наблюдения SEC'],['template_publications','Публикация версии и личное прочтение'],['valuation_summary','Диапазоны сохранённых ValuationRun'],['workbook_mapping / maps','WorkbookMapping — оригинал, карта, подтверждение'],['templates / calculations','TemplateVersion → CalculationRun → replay']],[430,722],160,460);
text(s,'Новая карта ссылается на предыдущую. Подтверждения и исходные числа\nсохраняются отдельно от проверенных фактов и эталонов AI Lab.',64,640,1152,65,26,amber);

s=slide('Технические проверки','docs/STAGE_9_REVIEW.md; tests/test_workbook_maps.py; scripts/check_postgres.py; check_workbook_maps.cjs; check_recovery.py. Синтетические данные.');
table(s,[['Проверка','Результат'],['Полный локальный pytest','391 passed / 1 skipped; OCR отдельно в Linux'],['Chrome','9 метрик + формула, подтверждения, расчёт и replay'],['PostgreSQL','Нет дублей; устаревшее редактирование отклонено'],['Чистое восстановление','41 таблица / 6 файлов / 15 HTTPS-сессий']],[400,752],165,400);
text(s,'Восстановлены оригинал книги, карта и подтверждения, общие публикации,\nистория SEC и AI-попытки. Проверены отзыв доступа и отказ ИИ.\nЭти проверки не подтверждают качество реальных финансовых моделей.',64,590,1152,110,27,amber);

s=slide('Четыре открытые задачи приёмки','docs/PROJECT_PLAN.md; PILOT_ACCEPTANCE.md; ISSUER_CORPUS.md; STAGE_6_ANSWERS.md; STAGE_7_ANSWERS.md.');
text(s,'GS-001 — продукт и реальный замер десяти минут\nGS-004 — ручные эталоны и качество ≥95%\nGS-023 — сеть фонда, носитель и перезапуск\nGS-024 — методика, реальные модели и Office',64,180,1152,250,34);
text(s,'Принятых реальных gold-фактов: 0.\nРучную сверку JPMorgan выполняете вы.\nПодключение Tailscale и носителя остаётся отложенным.',64,470,1152,140,29,amber);
text(s,'Допуск пилота: NO-GO до выполнения критериев. Год начинается после приёмки.',64,650,1152,40,26);

s=slide('Дальнейшая работа после контрольной точки','docs/STAGE_9_REVIEW.md, раздел 12 вопросов; PROJECT_RULES.md, пункты 6–7. Новая задача до ответов не начинается.');
text(s,'Рекомендация: первый реальный путь JPMorgan.',64,175,1152,70,36,green,true);
text(s,'Проверить данные и методику, затем измерить обновление.\nПодключить вашу книгу и определить нужные Excel-функции.\nИсправлять обнаруженные ограничения по реальному примеру.',64,295,1152,185,30);
text(s,'12 вопросов: приоритет следующей работы, вид книги, функции,\nпериоды, вёрстка экспорта, сравнение обновлений, настройка карты,\nсвязи с фактами, исключения, замер времени и приёмка форматов.',64,535,1152,120,27);
text(s,'Следующая задача — после ответов или явного поручения выбрать настройки.',64,670,1152,35,24,amber);

const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
const finalPath=path.join(output,'GoldenStock-Stage-9-2026-11-09-reviewed.pptx');
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...['2','8','9'].flatMap(n=>['--require-native-table-slide',n])],fontPolicy:{basis:'design',families:['Arial']},requiredNativeTableOwnerSlides:[2,8,9],requiredNativeChartOwnerSlides:[],verifyArtifactToolImport:true,receiptPath:path.join(build,'validation-delivery.json')});
const imported=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(let i=0;i<imported.slides.items.length;i++){
 const blob=await imported.export({slide:imported.slides.getItem(i),format:'png',scale:1});
 await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));
}
console.log(JSON.stringify(result));

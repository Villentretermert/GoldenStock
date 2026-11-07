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
const build=path.join(root,'.build-stage7-deck'), output=path.join(root,'deliverables');
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

let s=slide('','Состояние на 7 ноября 2026. docs/STAGE_7_REVIEW.md; docs/PROJECT_PLAN.md.');
text(s,'GoldenStock\nРабота с реальными отчётами',64,155,1152,210,58,green,true);
text(s,'Обзор GS-025–028\n7 ноября 2026',64,424,1152,95,31);
line(s,64,560,1152);
text(s,'24 из 28 задач завершены в техническом объёме.\nЧетыре задачи ожидают реальной приёмки.',64,590,1152,90,29,amber);

s=slide('Четыре доработки после этапа 6','docs/issues/GS-025.md; GS-026.md; GS-027.md; GS-028.md.');
table(s,[['Задача','Изменение','Результат'],['GS-025','Длинные PDF по порциям','JPMorgan 364 и HSBC 372 страницы'],['GS-026','Выбор строки и колонки','Переход к странице и подсветка суммы'],['GS-027','Крупные финансовые XLSX','Четыре книги обработаны полностью'],['GS-028','Предпросмотр входа ИИ','Длинный текст передаётся фрагментами']],[165,450,537],165,390);
text(s,'Все предложения ИИ и извлечённые факты требуют проверки аналитика.',64,605,1152,80,27,amber);

s=slide('Корпус для ручной разметки','docs/ISSUER_CORPUS.md; evaluation/datasets/issuer-corpus-v0.1/manifest.json. Резервные идентификаторы остаются локальными.');
table(s,[['Эмитент','Рабочие','Резерв','Всего'],['JPMorgan Chase','8','2','10'],['HSBC Holdings','8','2','10'],['Nu Holdings','8','2','10'],['Итого','24','6','30']],[552,200,200,200],155,320);
text(s,'25 PDF и 5 XLSX. В рабочих файлах 160 865 сырых элементов.\nПринятых эталонных фактов пока 0 из 500.',64,515,1152,100,28);
text(s,'Резерв требует проверки пересечений. Для нативного PPTX остаётся пробел.',64,640,1152,50,24,amber);

s=slide('Рабочее место проверки числа','docs/JPMORGAN_FIRST_REVIEW.md; design/previews/source-occurrence.png. Снимок синтетической проверки GS-026.');
await screen(s,'source-occurrence.png',40,150,800,510);
text(s,'Переход к PDF-странице\nсохраняет нумерацию оригинала.\n\nПовторяющуюся сумму\nаналитик выбирает по строке.\n\nReview подсвечивает\nименно выбранное вхождение.',865,175,350,370,27);
text(s,'JPMorgan ожидает вашей\nпроверки в кабинете.',865,590,350,85,26,amber);

s=slide('Предпросмотр фрагмента для локального ИИ','docs/AI_EVIDENCE_WINDOWS.md; design/previews/ai-window-desktop.png. Реальный UI, синтетический PDF и локальный Qwen.');
await screen(s,'ai-window-desktop.png',40,140,800,555);
text(s,'Аналитик видит точный вход\nдо отправки локальному Qwen.\n\nСледующий фрагмент\nзапускается отдельно.\n\nСохранённая задача содержит\nтот же текст и его происхождение.',865,170,350,390,27);
text(s,'Предложение остаётся\nunreviewed до ручного решения.',865,590,350,90,25,amber);

s=slide('Системный дизайн и оставшаяся приёмка','docs/ARCHITECTURE.md; docs/AI_EVIDENCE_WINDOWS.md; docs/PILOT_ACCEPTANCE.md. Зелёный обозначает техническую реализацию, охра ожидает реальной приёмки.');
node(s,'Браузер\nPython UI',64,165,245,100);node(s,'FastAPI и ACL\nВыбор текста',385,165,260,100);node(s,'PostgreSQL\nВерсии и аудит',735,165,310,100);
line(s,309,214,76,green);line(s,645,214,90,green);
node(s,'Файл / Extraction\nPDF, XLSX, PPTX',64,345,280,105);node(s,'Worker / AIRun\nОчередь задач',410,345,300,105);node(s,'OllamaProvider\nЛокальный Qwen',790,345,345,105);
line(s,344,396,66,green);line(s,710,396,80,green);
text(s,'Браузер обращается к API. Worker вызывает ИИ внутри частной Docker-сети.\nПодтверждённые факты поступают в расчёт, оценку и экспорт.',64,485,1152,90,27);
node(s,'Эталоны и методика\nGS-004 / GS-024',64,595,350,90,true);node(s,'Tailscale и носитель\nGS-023',455,595,330,90,true);node(s,'Допуск фонда\nGS-001 / GS-024',825,595,390,90,true);

s=slide('Компоненты и сущности кода','src/goldenstock/ai_evidence.py; ai_runs.py; models.py; extraction.py. Новая миграция в GS-028 не требуется, актуальная схема 0016.');
text(s,'Extraction и ExtractionCheckpoint',64,165,1152,45,30,green,true);
text(s,'Завершённое извлечение и отдельный прогресс длинного PDF.\nЧастичный PDF не попадает в расчёт.',64,223,1152,85,28);
text(s,'source_window и AIRun.input',64,340,1152,45,30,green,true);
text(s,'Функция выбирает диапазон исходного текста.\nОчередь фиксирует текст, SHA-256, локатор и курсор продолжения.',64,398,1152,90,28);
text(s,'Fact, Review и InputSnapshot',64,525,1152,45,30,green,true);
text(s,'Аналитик задаёт контекст и подтверждает факты.\nРасчёт работает с сохранённым проверенным набором.',64,583,1152,90,28);

s=slide('Результаты технических проверок','7 ноября 2026. Полный локальный pytest 277 passed / 1 skipped. .build-gs028/corpus-windows.json; scripts/check_browser.py, GS_QA_AI_WINDOWS=1 и GS_QA_AI=1. CI-кандидат b06b9962f50edab78c966b310b39c15b911a2f78.');
text(s,'277',64,160,300,100,76,green,true);text(s,'тестов прошли локально\nОдин OCR-тест пропущен',64,280,350,100,26);
text(s,'215',470,160,300,100,76,green,true);text(s,'длинных элементов\nв 24 рабочих документах',470,280,350,100,26);
text(s,'430',900,160,300,100,76,green,true);text(s,'окон сохраняют\nисходный текст целиком',900,280,315,100,26);
line(s,64,425,1152);
text(s,'Chrome проверил новый путь и 18 прежних сценариев.\nЛокальный Qwen получил ровно показанный вход.\nЧужие аккаунты не могут читать и отправлять этот текст.',64,467,1152,145,29);
text(s,'Реальные accuracy, precision, coverage и время до 10 минут ещё не измерены.',64,644,1152,45,24,amber);

s=slide('Что остаётся до запуска фонда','docs/PILOT_ACCEPTANCE.md; docs/STAGE_6_ANSWERS.md. Tailscale и носитель пользователь подключит позже.');
text(s,'Данные и методика',64,165,520,55,32,green,true);
text(s,'500 проверенных фактов, включая 100 holdout\nРеальные модели JPMorgan, HSBC и Nu\nПодписание методики и проверка Office\nПробелы английских источников и PPTX',64,250,545,235,27);
text(s,'Эксплуатация',690,165,525,55,32,green,true);
text(s,'Tailscale фонда и второе устройство\nОтдельный носитель и перезапуск Windows\n45 документов за рабочий день\nРезерв GPU и полный путь до 10 минут',690,250,525,235,27);
line(s,64,535,1152);
text(s,'GS-001, GS-004, GS-023 и GS-024 сохраняют REVIEW.\nНачало годового пилота зависит от подписания приёмки.',64,580,1152,95,30,amber);

s=slide('Следующий этап','docs/STAGE_7_REVIEW.md. Ответы контрольной точки требуются по PROJECT_RULES.md, пункт 7.');
text(s,'Сначала уточнить сценарий десяти минут\nи выбрать ближайшее улучшение кабинета.',64,165,1152,130,36,green,true);
text(s,'Рекомендуемый порядок после ответов\nПодготовка разметки, первый проверенный JPMorgan, затем HSBC и Nu.\nЗамер полного процесса покажет, где нужна автоматизация.',64,335,1152,180,30);
line(s,64,570,1152);
text(s,'12 вопросов сохранены в тексте обзора.\nРучная сверка JPMorgan остаётся отложенной до работы в кабинете.',64,605,1152,80,27,amber);

const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:path.join(output,'GoldenStock-Stage-7.pptx'),pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','2','--require-native-table-slide','3'],fontPolicy:{basis:'design',families:['Arial']},requiredNativeTableOwnerSlides:[2,3],requiredNativeChartOwnerSlides:[],verifyArtifactToolImport:true,receiptPath:path.join(build,'validation-delivery.json')});
// Render the final exported file, including its native tables, for visual review.
const imported=await PresentationFile.importPptx(await FileBlob.load(path.join(output,'GoldenStock-Stage-7.pptx')));
for(let i=0;i<imported.slides.items.length;i++){
 const blob=await imported.export({slide:imported.slides.getItem(i),format:'png',scale:1});
 await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));
}
console.log(JSON.stringify(result));

// Local stage review using the established GoldenStock visual style. No uploads.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd(), home=process.env.USERPROFILE;
const runtime=path.join(home,'.cache/codex-runtimes/codex-primary-runtime/dependencies');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const skill=path.join(home,'.codex/plugins/cache/openai-primary-runtime/presentations/26.1020.11348/skills/presentations');
const {Presentation,PresentationFile}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')));
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')));
const build=path.join(root,'.build-stage5-deck'), output=path.join(root,'deliverables');
await fs.mkdir(build,{recursive:true});await fs.mkdir(output,{recursive:true});
const p=Presentation.create({slideSize:{width:1280,height:720}});
function text(s,t,x,y,w,h,size=27,color='#193B30',bold=false){const b=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});b.text=t;b.text.style={typeface:'Arial',fontSize:size,color,bold};return b;}
function slide(title){const s=p.slides.add();s.background.fill='#F5F5EF';if(title)text(s,title,65,42,1150,80,39,'#193B30',true);return s;}
function block(s,t,x,y,w,h,done=true){const b=s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:done?'#E2EDE5':'#F0E7D5',line:{fill:done?'#193B30':'#9B742B',width:1}});text(s,t,x+16,y+18,w-32,h-25,23,done?'#193B30':'#735B22',true);return b;}
let s=slide();text(s,'GoldenStock\nМодель, оценка и экспорт',65,145,1150,190,58,'#193B30',true);text(s,'Обзор этапа GS-017–020\n30 октября 2026',65,430,1150,110,31);text(s,'Технический этап завершён. Реальная методическая приёмка впереди.',65,615,1150,55,24,'#735B22');
s=slide('Четыре задачи: результаты');
text(s,'GS-017   Версии XLSX-шаблонов и общие очищенные структуры\nGS-018   Decimal-расчёт, три сценария, контрольные равенства\nGS-019   DDM / FCFE, P/E / P/B и пользовательские показатели\nGS-020   XLSX, PDF и PPTX из сохранённой личной оценки',65,155,1150,300,29);
text(s,'Источники, предпосылки, решения аналитика и версии сохраняются.\nОтозванная проверка помечает результат как исторический.\nИИ не выполняет финансовую арифметику.',65,530,1150,140,27,'#66756C');
s=slide('Путь аналитика в приложении');
s.images.add({blob:new Uint8Array(await fs.readFile(path.join(root,'design/previews/valuation-desktop.png'))),contentType:'image/png',position:{left:40,top:140,width:790,height:540},fit:'contain'});
text(s,'Документ → проверенные факты\n\nВерсия Excel-шаблона → расчёт\n\nМетод и предпосылки → оценка\n\nDownload → XLSX / PDF / PPTX',850,165,365,365,24);
text(s,'На экране синтетический пример.\nОценки пока доступны автору.',850,585,365,80,22,'#735B22');
s=slide('Система: готовое и оставшееся');
block(s,'Браузер\nPython UI',65,155,250,115);block(s,'FastAPI\nСессии и ACL',390,155,250,115);block(s,'PostgreSQL\nВерсии и аудит',715,155,280,115);
text(s,'→',333,185,45,45,35);text(s,'→',658,185,45,45,35);
block(s,'Факты / Review\nПодтверждение',65,330,250,115);block(s,'CalculationRun\nDecimal / сценарии',390,330,250,115);block(s,'ValuationRun\nXLSX / PDF / PPTX',715,330,280,115);
text(s,'→',333,360,45,45,35);text(s,'→',658,360,45,45,35);
text(s,'Локальный ИИ / RAG: предлагает контекст; браузер обращается только к API.',65,475,1150,55,25);
block(s,'GS-021: AI Lab',65,565,250,85,false);block(s,'GS-022: мониторинг',350,565,270,85,false);block(s,'GS-023: VPN / backup',655,565,300,85,false);text(s,'GS-024\nПриёмка',990,577,220,80,23,'#735B22',true);
s=slide('Код и сущности, которые стоит знать');
text(s,'TemplateVersion     Карта ячеек, определения и допустимые формулы\nCalculationRun       Входы сценариев, Decimal-результат, проверки\nValuationRun          Метод, периметр, котировка и чувствительность\nexports.py              ACL → SHA-256 → replay → статус проверки\nexport_content.py   Единые числа и происхождение для трёх форматов',65,150,1150,330,27);
text(s,'Пример: source_key связывает вход оценки с полем CalculationRun.\nВ XLSX это ссылка Calc → Val → Summary. Изменение исходной прибыли\nпересчитывает модель; сохранённый серверный снимок остаётся прежним.',65,545,1150,130,25,'#66756C');
s=slide('Что проверено');
text(s,'197 тестов прошли в полном локальном прогоне; 1 OCR skipped.\n9 экспортных тестов прошли после уточнений.\n31 браузерный сценарий: без JS-ошибок и внешних запросов.\nPostgreSQL: конкурентность, replay и восстановление очереди.',65,150,1150,250,28);
text(s,'XLSX: независимый пересчёт четырёх методов, всех точек чувствительности,\nтрёх сценариев, источника прибыли, котировки, акций и граничных входов.\nPDF/PPTX: проверены текст, таблицы, длинные примечания и рендеры.',65,460,1150,140,26);
text(s,'Excel и PowerPoint desktop не запускались. Числа примеров синтетические.',65,645,1150,40,23,'#735B22');
s=slide('Что пока не подтверждено');
text(s,'95% accuracy на независимом реальном корпусе (GS-004).\nПолный реальный расчёт JPMorgan и методическая приёмка.\nПользовательский шаблон Excel: пока используется контракт v1.\nОбщие оценки: сейчас личные; общими бывают структуры шаблонов.\nУдалённый доступ, резервное восстановление и нагрузка 15 аналитиков.',65,150,1150,340,28);
text(s,'DDM/FCFE v1: пять календарных лет от конца года, cost of equity.\nНет автоматической конвертации валют, ADR или выбора comparables.\nExcel использует ~15 цифр; серверный Decimal — 34.',65,550,1150,125,26,'#735B22');
s=slide('Следующий этап после ваших ответов');
text(s,'GS-021   AI Lab: сравнение моделей на одинаковых входах\nGS-022   Мониторинг официальной финансовой отчётности\nGS-023   Защищённый удалённый доступ и резервирование\nGS-024   Приёмка и запуск годового пилота',65,155,1150,280,30);
text(s,'Сначала нужны сопоставимые измерения качества, затем мониторинг\nи подключение коллег. GS-001 и GS-004 остаются на приёмке.\nКонтрольная точка: 12 вопросов в STAGE_5_REVIEW.md.\nДо ответов следующая задача не начинается.',65,520,1150,155,26,'#735B22');
for(let i=0;i<p.slides.items.length;i++){const blob=await p.export({slide:p.slides.getItem(i),format:'png',scale:1});await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));}
const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:path.join(output,'GoldenStock-Stage-5-final.pptx'),pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],fontPolicy:{basis:'design',families:['Arial']},requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],verifyArtifactToolImport:true,receiptPath:path.join(build,'validation-final.json')});console.log(JSON.stringify(result));

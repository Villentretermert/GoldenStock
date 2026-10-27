// Local-only stage review. No cloud calls or uploads.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd();
const home=process.env.USERPROFILE;
const runtime=path.join(home,'.cache/codex-runtimes/codex-primary-runtime/dependencies');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const skill=path.join(home,'.codex/plugins/cache/openai-primary-runtime/presentations/26.1020.11348/skills/presentations');
const {Presentation,PresentationFile}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')));
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')));
const build=path.join(root,'.build-status-20261025');
const output=path.join(root,'deliverables');
await fs.mkdir(build,{recursive:true});await fs.mkdir(output,{recursive:true});
const p=Presentation.create({slideSize:{width:1280,height:720}});
function text(s,t,x,y,w,h,size=26,color='#193B30',bold=false){const b=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});b.text=t;b.text.style={typeface:'Arial',fontSize:size,color,bold};return b;}
function slide(title, sources='docs/STAGE_4_REVIEW.md'){const s=p.slides.add();s.background.fill='#F5F5EF';if(title)text(s,title,64,42,1152,90,40,'#193B30',true);s.speakerNotes.text='Срез проекта на 25.10.2026. Последний код: 89db8fc. Источники в репозитории: '+sources;return s;}
function box(s,t,x,y,w,h,color='#DFEADD'){s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:color,line:{fill:'#A7B4A7',width:1}});text(s,t,x+14,y+14,w-28,h-20,24);}

let s=slide('','docs/PROJECT_PLAN.md; docs/issues/GS-001.md–GS-024.md; docs/STAGE_4_REVIEW.md');
text(s,'GoldenStock',64,90,1150,100,68,'#193B30',true);
text(s,'Текущий статус проекта',64,240,1140,100,48,'#193B30',true);
text(s,'25 октября 2026\nЛокальный веб-пилот для финансовых аналитиков',64,385,1140,115,28);
text(s,'Работает путь от документа до проверенных фактов и сводки.\nФинансовый расчёт и оценка компании ещё впереди.',64,575,1140,95,28,'#735B22');

s=slide('14 задач завершены в заявленном объёме','docs/issues/GS-001.md–GS-024.md');
for(const [n,label,desc,x,color] of [['14','DONE','GS-002–003\nGS-005–016',64,'#285641'],['2','REVIEW','GS-001: открытые решения\nGS-004: реальный эталон',470,'#735B22'],['8','TODO','GS-017–024\nРасчёт, экспорт, запуск',875,'#66756C']]){text(s,n,x,175,320,125,98,color,true);text(s,label,x,325,320,50,27,color,true);text(s,desc,x,400,350,125,25);}
text(s,'Это статусы задач, а не процент готовности продукта.\nДо полного закрытия плана остаются 8 новых задач и 2 задачи на проверке.',64,590,1150,85,25,'#735B22');

s=slide('Что получает аналитик сегодня','docs/PRD.md; docs/ANALYST_REVIEW.md; docs/STAGE_4_REVIEW.md');
text(s,'01   Войти в личный кабинет и выбрать компанию\n02   Загрузить PDF, PPTX или XLSX до 50 MB\n03   Извлечь текст и таблицы, включая OCR английских сканов\n04   Получить предложения метрик и проверить их по оригиналу\n05   Подтвердить факты и сохранить проверенный набор входов\n06   Получить сводку с цитатами и отмеченными пробелами',64,160,1150,385,29);
text(s,'Пилот: один фонд, 15 аналитиков, пять согласованных компаний.\nТолько веб. Все AI-вызовы проходят через сервер приложения.',64,590,1150,90,25,'#66756C');

s=slide('Проверка факта привязана к оригиналу','docs/ANALYST_REVIEW.md; design/previews/review-fact.png');
s.images.add({blob:new Uint8Array(await fs.readFile(path.join(root,'design/previews/review-fact.png'))),contentType:'image/png',position:{left:45,top:145,width:790,height:510},fit:'contain'});
text(s,'Аналитик видит источник,\nединицы, период и периметр.\n\nКаждый включённый факт\nдолжен быть подтверждён.\n\nОтклонение с причиной\nсохраняется в истории.',865,165,350,350,25);
text(s,'Расхождение прибыли или\nкапитала блокирует набор.\nОкругление учитывается.',865,545,350,110,24,'#735B22');
s.speakerNotes.append('\nСкриншот синтетического QA, а не клиентская отчётность. Скриншот сделан до текущего статуса.');

s=slide('Публичные сводки проверены на трёх компаниях','docs/STAGE_4_REVIEW.md; src/goldenstock/public_sources.py');
text(s,'JPMorgan Chase, HSBC и Nu Holdings',64,155,1150,65,35,'#285641',true);
text(s,'SEC companyfacts загружается в локальный снимок.\nУ результата есть период, цитата, источник и оригинал JSON.\nИИ выбирает факты, сервер выводит их дословно.',64,260,1150,195,29);
text(s,'7,3–9,1 с',64,490,450,90,60,'#285641',true);
text(s,'Время inference в одном прогоне 24 октября.\nНе включает гарантию ожидания в очереди.',520,505,680,85,25);
text(s,'Выборка до четырёх метрик не покрывает все отчёты.\nАнглийское покрытие Сбера и Т-Технологий пока остаётся пробелом.',64,610,1150,75,23,'#735B22');

s=slide('Устройство системы и оставшиеся блоки','docs/STAGE_4_REVIEW.md; docs/adr/0004_local_ai_orchestration.md');
box(s,'Браузер\nPython-страницы',64,155,300,95);
box(s,'FastAPI\nСессии и права',490,155,300,95);
box(s,'Worker\nОчередь заданий',916,155,300,95);
text(s,'→',398,172,60,65,43);text(s,'→',824,172,60,65,43);
box(s,'Файлы и SEC\nДокументы и снимки',64,340,300,100);
box(s,'PostgreSQL\nФакты, версии, AIRun',490,340,300,100);
box(s,'Локальный Ollama\nДва профиля Qwen',916,340,300,100);
text(s,'→',398,357,60,65,43);text(s,'↕',613,265,60,65,43);text(s,'↕',1038,265,60,65,43);
text(s,'Работает локально: закрытые документы не уходят во внешние AI API.',64,475,1150,55,24,'#285641');
box(s,'Впереди: Excel → расчёт → оценка → XLSX / PDF / PPTX',64,560,1152,70,'#F2E9D3');
text(s,'Позже: AI Lab, мониторинг отчётности, защищённый доступ и восстановление.',64,653,1150,40,23,'#735B22');

s=slide('Код и сущности сохраняют происхождение данных','src/goldenstock/models.py; docs/LOCAL_AI.md; docs/adr/0004_local_ai_orchestration.md');
text(s,'Extraction / Fact / FactReview / InputSnapshot',64,160,1150,60,32,'#285641',true);
text(s,'Извлечённые данные, нормализованный факт, решение аналитика\nи неизменяемый набор входов для будущего расчёта.',64,240,1150,90,27);
text(s,'AIRun / PublicSnapshot',64,365,1150,60,32,'#285641',true);
text(s,'Версии модели, входы, результаты и ошибки запуска.\nПубличный оригинал SEC с SHA-256 и временем получения.',64,445,1150,100,27);
text(s,'Ключевые модули: extraction.py, normalization.py, reviews.py,\nai_runs.py, public_sources.py. Браузер обращается только к API.',64,600,1150,85,24,'#66756C');

s=slide('ИИ можно заменить, знания хранятся отдельно','docs/LOCAL_AI.md; docs/adr/0004_local_ai_orchestration.md');
text(s,'Wrapper в inference.py',64,160,530,55,30,'#285641',true);
text(s,'Единый интерфейс профилей.\nЗакреплены версии весов Qwen.\nЗамена требует проверки качества.',64,235,530,170,27);
text(s,'RAG в knowledge.py',675,160,530,55,30,'#285641',true);
text(s,'Лексический поиск подтверждённых\nличных фактов перед генерацией.\nПолного семантического индекса нет.',675,235,530,170,27);
text(s,'Как пользоваться',64,455,1150,55,30,'#285641',true);
text(s,'Review: подтвердить факты. Create summary: получить сводку.\nExport private knowledge pack: выгрузить факты и происхождение в JSON.',64,525,1150,95,26);
text(s,'Перенос знаний не означает обучение весов. MCP, CrewAI и LangGraph отложены.',64,652,1150,40,23,'#735B22');

s=slide('Проверки подтверждают механику, качество ещё открыто','CHANGELOG.md; docs/STAGE_4_REVIEW.md; evaluation/results/gs013-prompt-v5-gpu.json');
text(s,'105',64,165,300,115,82,'#285641',true);text(s,'тестов до исправления\nчислового пересказа',64,300,340,95,25);
text(s,'13',470,165,300,115,82,'#285641',true);text(s,'целевых тестов после\nисправления, с регрессией',470,300,350,95,25);
text(s,'18',880,165,300,115,82,'#285641',true);text(s,'браузерных сценариев\nпосле исправления',880,300,340,95,25);
text(s,'Один OCR-тест пропущен в Windows, ранее проверен в Docker.\nЧисла тестов не суммируются. Это результаты прогонов 24 октября.',64,440,1150,100,25);
text(s,'Реальный эталон GS-004 не размечен. Accuracy 95% не подтверждена.\nНагрузка 45 документов в день и 15 сотрудников пока не проверена.',64,595,1150,90,26,'#735B22');

s=slide('Основные ограничения перед запуском фонда','docs/STAGE_4_REVIEW.md; docs/LOCAL_AI.md; docs/PROJECT_PLAN.md');
text(s,'Числовой пересказ',64,155,350,50,28,'#735B22',true);text(s,'На Nu обнаружено увеличение прибыли в 10 раз.\nИсправление выводит исходные цитаты. Пробелы ИИ требуют проверки.',430,155,780,100,25);
text(s,'Ресурсы компьютера',64,300,350,50,28,'#735B22',true);text(s,'GPU 12 GB, один AI-вызов одновременно.\nМинимум 6 623 MiB свободно в одном тесте не гарантирует резерв.',430,300,780,100,25);
text(s,'Доступ и эксплуатация',64,445,350,50,28,'#735B22',true);text(s,'Есть прикладные права и изоляция личных объектов.\nRLS, защищённый удалённый доступ и проверка восстановления впереди.',430,445,780,100,25);
text(s,'Оценка компании, денежная смета эксплуатации и итоговая приёмка ещё не готовы.',64,625,1150,60,24,'#735B22');

s=slide('Осталось восемь новых задач','docs/PROJECT_PLAN.md; docs/issues/GS-017.md–GS-024.md');
text(s,'Следующий этап',64,155,530,55,31,'#285641',true);
text(s,'GS-017  Контракт Excel-шаблона\nGS-018  Детерминированный расчёт\nGS-019  Оценка и бизнес-показатели\nGS-020  XLSX, PDF и PPTX',64,245,550,270,27);
text(s,'Подготовка к пилоту',685,155,530,55,31,'#285641',true);
text(s,'GS-021  AI Lab и сравнение моделей\nGS-022  Новая отчётность и уведомления\nGS-023  Доступ и резервирование\nGS-024  Приёмка и годовой пилот',685,245,550,270,27);
text(s,'Сначала согласуем шаблон, затем проверим расчёт на одном примере.\nGS-017 ожидает ответы контрольной точки. GS-001 и GS-004 остаются REVIEW.',64,590,1150,95,25,'#735B22');

s=slide('Решения перед Excel-этапом: 1–6','docs/STAGE_4_REVIEW.md: контрольные вопросы');
text(s,'1. Подходит ли сводка из дословных фактов с цитатами?\n\n2. Показывать пробелы ИИ как непроверенные или скрыть?\n\n3. Первая компания: JPMorgan, HSBC или Nu?\n\n4. Создать демонстрационный шаблон до получения вашего?\n\n5. Горизонт прогноза: 3, 5 или 10 лет?\n\n6. Прогноз годовой или квартальный?',64,155,1150,490,28);

s=slide('Решения перед Excel-этапом: 7–12','docs/STAGE_4_REVIEW.md: контрольные вопросы');
text(s,'7. Сразу три сценария или сначала только базовый?\n\n8. Валюта отчётности или единая USD с правилом курсов?\n\n9. Какие предпосылки аналитик редактирует вручную?\n\n10. При пробеле блокировать расчёт или разрешать ручную предпосылку?\n\n11. В экспорте важнее инвесткомитет или подробная проверка модели?\n\n12. При занятой GPU ждать в очереди или использовать медленный CPU?',64,155,1150,490,27);
for(let i=0;i<p.slides.items.length;i++){const blob=await p.export({slide:p.slides.getItem(i),format:'png',scale:1});await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));}
const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:path.join(output,'GoldenStock-Status-2026-10-25.pptx'),pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],fontPolicy:{basis:'design',families:['Arial']},requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],verifyArtifactToolImport:true,receiptPath:path.join(build,'validation-final.json')});console.log(JSON.stringify(result));

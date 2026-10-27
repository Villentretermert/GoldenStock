// Local-only stage review. No cloud calls or uploads.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd();
const home=process.env.USERPROFILE;
const runtime=path.join(home,'.cache/codex-runtimes/codex-primary-runtime/dependencies');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const skill=path.join(home,'.codex/plugins/cache/openai-primary-runtime/presentations/26.1017.31632/skills/presentations');
const {Presentation,PresentationFile}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')));
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')));
const build=path.join(root,'.build-stage2-deck');
const output=path.join(root,'deliverables');
await fs.mkdir(build,{recursive:true});await fs.mkdir(output,{recursive:true});
const p=Presentation.create({slideSize:{width:1280,height:720}});
function text(s,t,x,y,w,h,size=26,color='#193B30',bold=false){const b=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});b.text=t;b.text.style={typeface:'Arial',fontSize:size,color,bold};return b;}
function slide(title){const s=p.slides.add();s.background.fill='#F5F5EF';if(title)text(s,title,70,45,1140,80,40,'#193B30',true);return s;}
let s=slide();text(s,'GoldenStock\nКабинет, доступ и файлы',80,170,1120,170,52,'#193B30',true);text(s,'Обзор GS-005–008\n22 октября 2026 · локальный пилот',80,410,1100,120,29,'#66756C');
s=slide('Результаты этапа');text(s,'GS-005   Python и Docker\nGS-006   Аккаунты, организации и права\nGS-007   Каталог и личное избранное\nGS-008   Оригиналы и очередь проверки',70,160,1140,300,31);text(s,'Пока нет OCR, финансовых расчётов и работающей модели ИИ.\nУдалённый доступ проверяется отдельно в GS-023.',70,530,1140,100,25,'#735B22');
s=slide('Границы доступа');text(s,'Аналитик',70,170,520,60,31,'#193B30',true);text(s,'Свои файлы и избранное\nОбщие названия черновиков фонда\nНет доступа к другому фонду',70,250,530,240);text(s,'Администратор аккаунтов',680,170,530,60,31,'#193B30',true);text(s,'Создание и отключение аккаунтов\nОтзыв активных сессий\nБез доступа к чужим личным файлам',680,250,530,240);text(s,'auth.py — сессия и ACL; accounts.py — управление аккаунтами и черновиками.\nRLS и TLS/VPN ещё не реализованы.',70,550,1140,100,23,'#735B22');
s=slide('Система: что работает и что впереди');
for(const [t,x,y,w,color]of [['Браузер\nPython-страницы',70,180,260,'#DFECDD'],['FastAPI\nСессия + ACL',390,180,260,'#DFECDD'],['PostgreSQL\nАккаунты, версии, jobs',730,180,460,'#DFECDD'],['Worker\nSHA-256 + retry',390,350,260,'#DFECDD'],['FileStore\nОригиналы в volume',730,350,460,'#DFECDD'],['Ollama endpoint\nВеса пока не загружены',70,520,530,'#F1E6CB'],['Далее: OCR → факты → RAG → оценка\nGS-009–020 ещё не реализованы',660,520,530,'#F1E6CB']]){const b=s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:110},fill:color,line:{fill:'#B9C9BA',width:1}});b.text=t;b.text.style={typeface:'Arial',fontSize:24,color:'#193B30'};}
text(s,'→',340,205,45,50,32);text(s,'→',670,205,45,50,32);text(s,'↓',500,295,45,50,32);text(s,'→',670,375,45,50,32);text(s,'Зелёный — реализовано. Охра — ограничено или впереди. Браузер не обращается к ИИ.',70,655,1140,40,20,'#66756C');
s=slide('Работающий кабинет');s.images.add({blob:new Uint8Array(await fs.readFile(path.join(root,'design/previews/workspace-desktop.png'))),contentType:'image/png',position:{left:70,top:145,width:760,height:528},fit:'contain'});text(s,'Личное избранное\nПять компаний в каталоге\nКандидаты отмечены\nНет выдуманных оценок',870,170,340,310,27);text(s,'Синтетический QA-аккаунт.\nДоступ после теста отозван.',870,535,340,110,22,'#66756C');
s=slide('Оригиналы и восстановление задач');text(s,'Document → DocumentVersion → Job → JobEvent',70,160,1140,60,30,'#193B30',true);text(s,'documents.py  Проверяет права, принимает оригинал, создаёт версию и задачу.\nstorage.py       Хранит файл по внутреннему ключу; считает SHA-256.\njobs.py           Выдаёт lease, повторяет сбои, отклоняет старого исполнителя.\nworker.py        Проверяет целостность и записывает результат.',70,270,1140,230,25);text(s,'Один Idempotency-Key + один запрос → одна версия и одна задача.\nПроверка целостности не означает извлечение данных или антивирусный анализ.',70,550,1140,110,24,'#735B22');
s=slide('Результаты проверок');text(s,'36',70,175,260,150,100,'#285641',true);text(s,'автоматических тестов проходят',70,350,430,110,29);text(s,'PostgreSQL: конкурентные загрузки и захват задачи\nАварийный выход процесса: задача восстановлена\nБраузер: вход → файл → скачивание → выход\nНет ошибок JS и мобильного переполнения',560,185,650,290,27);text(s,'Это проверка приложения, а не измерение accuracy ИИ.\nGitHub Actions подготовлен, но ещё не запускался на опубликованном коде.',70,550,1140,110,24,'#735B22');
s=slide('Следующий этап: проверяемые финансовые факты');text(s,'GS-009   Разрешённые источники и точные эмитенты\nGS-010   Извлечение PDF, PPTX, XLSX и OCR\nGS-011   Метрики, единицы, периоды и противоречия\nGS-012   Рабочее место проверки аналитика',70,160,1140,290,30);text(s,'Сначала источники и проверяемые факты — они нужны для оценки компании.\nДо GS-009: ответы на вопросы контрольной точки.\nGS-001 и GS-004 сохраняют открытые вопросы согласования и разметки.',70,520,1140,140,25,'#735B22');
for(let i=0;i<p.slides.items.length;i++){const blob=await p.export({slide:p.slides.getItem(i),format:'png',scale:1});await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));}
const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:path.join(output,'GoldenStock-Stage-2-final.pptx'),pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],fontPolicy:{basis:'design',families:['Arial']},requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],verifyArtifactToolImport:true,receiptPath:path.join(build,'validation-final.json')});console.log(JSON.stringify(result));




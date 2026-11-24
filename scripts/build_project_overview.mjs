// Editable local deck. Set GS_RUNTIME_ROOT to the bundled dependency runtime.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {slides as content} from '../assets/project_overview_content.mjs';
const slides=process.env.GS_LAYOUT_PROOF==='1'?[content[0],content[1],content[2],content[5],content[31],content[54]]:content;
const root=process.cwd(),runtime=process.env.GS_RUNTIME_ROOT;
if(!runtime)throw Error('Set GS_RUNTIME_ROOT using the workspace dependency tool');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const skill=path.join(process.env.USERPROFILE,'.codex/plugins/cache/openai-primary-runtime/presentations/26.1123.11515/skills/presentations');
const {Presentation,PresentationFile,FileBlob,registerPdfFontFace}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')));
for(const [weight,file] of [[400,'arial.ttf'],[700,'arialbd.ttf']])registerPdfFontFace({family:'Arial',style:'normal',weight,source:new Uint8Array(await fs.readFile(path.join(process.env.WINDIR,'Fonts',file)))});
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')));
const build=path.join(root,'.build-overview/deck'),out=path.join(root,'deliverables');
await fs.mkdir(build,{recursive:true});await fs.mkdir(out,{recursive:true});
if(process.env.GS_WAIT_SCREENSHOTS==='1'){
 for(let attempt=0;attempt<180;attempt++){
  const missing=[];
  for(const d of slides.filter(x=>x.kind==='screen'))try{await fs.access(path.join(root,'design/previews',d.file));}catch{missing.push(d.file);}
  if(!missing.length)break;
  if(attempt===179)throw Error('Missing recorded screenshots: '+missing.join(', '));
  if(attempt%12===0)console.log('Waiting for '+missing.length+' actual demo screenshots.');
  await new Promise(r=>setTimeout(r,5000));
 }
}
const p=Presentation.create({slideSize:{width:1600,height:900}});
const C={bg:'#F5F5EF',green:'#193B30',gold:'#B99753',ink:'#233D32',muted:'#5C7165',line:'#CCD8CF',wash:'#E4EDE5',amber:'#8A5C13'};
function tx(s,t,x,y,w,h,size=28,color=C.ink,bold=false){
 const b=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 b.text=t;b.text.style={typeface:'Arial',fontSize:size,color,bold};return b;
}
function rect(s,x,y,w,h,fill,line='none'){return s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill,line:{fill:line,width:line==='none'?0:1}});}
function rule(s,y){rect(s,64,y,1472,2,C.line);}
const tableOwners=[];let part='Обзор проекта';
for(let i=0;i<slides.length;i++){
 const d=slides[i],s=p.slides.add();s.background.fill=C.bg;
 if(d.kind==='section')part=d.title;
 s.speakerNotes.text=`${d.title}\n\n${d.note||''}\n\nИсточники: ${d.source}\n\nСостояние проекта на 24 ноября 2026. Экраны и финансовые примеры синтетические. Реальная приёмка не подтверждена.`;
 if(!['cover','section','closing'].includes(d.kind)){
  tx(s,part.toUpperCase(),64,32,1200,30,18,C.muted,true);
  tx(s,d.title,64,86,1472,116,d.title.length>78?44:48,C.green,true);
  const footer=d.kind==='screen'?(d.file==='section-context-filled.png'?'GoldenStock · Сохранённая синтетическая проверка Qwen3 4B':'GoldenStock · Учебный экран · 24 ноября 2026'):'GoldenStock · 24 ноября 2026 · технический пилот';
  rule(s,822);tx(s,footer,64,840,1320,30,18,C.muted);
  tx(s,String(i+1).padStart(2,'0'),1474,838,60,32,20,C.muted,true);
 }
 if(d.kind==='cover'){
  rect(s,0,0,1600,900,C.green);
  tx(s,'GOLDENSTOCK',72,64,1450,50,25,'#CFB67C',true);
  tx(s,'От отчёта компании\nк проверенной модели\nи оценке',72,205,1450,320,78,'#FFFFFF',true);
  tx(s,d.body[1],72,635,1450,55,32,'#E3EADC');
  tx(s,d.body[2],72,724,1450,55,28,'#CFB67C');
  tx(s,'Полный обзор продукта, реализации и открытой приёмки',72,822,1450,35,22,'#C2D3C5');
 }else if(d.kind==='section'){
  rect(s,0,0,1600,900,C.green);
  tx(s,d.body[0],70,64,1400,170,140,'#CFB67C',true);
  tx(s,d.title,70,337,1450,180,76,'#FFFFFF',true);
  tx(s,d.body[1],74,595,1390,135,36,'#E3EADC');
  tx(s,'GoldenStock · '+String(i+1),74,830,1400,35,20,'#C2D3C5');
 }else if(d.kind==='status'){
  d.body.forEach((v,j)=>{const x=64+j*500;tx(s,v[0],x,286,460,130,94,j===2?C.amber:C.green,true);tx(s,v[1],x,443,440,170,32);});
  tx(s,'Открыты GS-001, GS-004, GS-023 и GS-024.\nРеальные 95%, десять минут и полевая эксплуатация ещё не подтверждены.',64,675,1470,95,30,C.amber);
 }else if(d.kind==='text'){
  const count=d.body.length,step=count===4?136:175;
  d.body.forEach((v,j)=>{const y=228+j*step;tx(s,v[0],64,y,350,60,32,C.green,true);tx(s,v[1],460,y,1060,step-20,32);if(j<count-1)rect(s,64,y+step-22,1472,1,C.line);});
 }else if(d.kind==='table'||d.kind==='questions'){
  const n=d.body[0].length,widths=d.kind==='questions'?[120,1352]:n===2?[520,952]:n===3?[295,625,552]:[155,310,180,827];
  const h=d.body.length>5?568:530;
  const t=s.tables.add({rows:d.body.length,columns:n,left:64,top:220,width:1472,height:h,columnWidths:widths,values:d.body});
  t.borders.assign({style:'solid',fill:C.line,width:1});
  for(let r=0;r<d.body.length;r++)for(let c=0;c<n;c++){
   const cell=t.getCell(r,c);cell.fill=r===0?C.green:(r%2?C.bg:'#EBF0E9');
   cell.text.style={typeface:'Arial',fontSize:27,color:r===0?'#FFFFFF':C.ink,bold:r===0||c===0};
   if(r>0 && /\b(REVIEW|pending)\b/.test(d.body[r][c])){cell.fill='#F4E7CC';cell.text.style={typeface:'Arial',fontSize:27,color:C.amber,bold:c===0};}
  }
  tableOwners.push(i+1);
 }else if(d.kind==='screen'){
  const bytes=await fs.readFile(path.join(root,'design/previews',d.file));
  s.images.add({blob:new Uint8Array(bytes),contentType:'image/png',position:{left:40,top:198,width:1024,height:618},fit:'contain'});
  d.body.forEach((v,j)=>tx(s,v,1100,231+j*(d.body.length===4?132:170),430,d.body.length===4?118:155,29));
 }else if(d.kind==='flow'){
  const points=[[64,242],[578,242],[1092,242],[1092,504],[578,504],[64,504]],boxes=[];
  d.body.forEach((v,j)=>{const [x,y]=points[j],pending=d.title==='Следующий путь к допуску пилота'||v[0]==='Tailscale / TLS';boxes.push(rect(s,x,y,444,184,pending?'#F4E7CC':C.wash,C.line));tx(s,v[0],x+22,y+23,400,50,32,pending?C.amber:C.green,true);tx(s,v[1],x+22,y+87,398,84,27);});
  for(const [a,b]of d.links){const from=points[a],to=points[b];let fromSide='right',toSide='left';if(from[1]!==to[1]){fromSide='bottom';toSide='top';}else if(from[0]>to[0]){fromSide='left';toSide='right';}
   s.shapes.connect(boxes[a],boxes[b],{kind:'elbow',fromSide,toSide,line:{fill:C.gold,width:3},tail:{type:'arrow',width:'med',length:'med'}});
  }
  const caption=d.note.length>230?d.note.slice(0,d.note.lastIndexOf('.',230)+1):d.note;
  tx(s,caption||'Источники и технические ограничения приведены в заметках докладчика.',64,733,1472,75,25,C.muted);
 }else if(d.kind==='closing'){
  rect(s,0,0,1600,900,C.green);tx(s,d.title,72,130,1450,240,66,'#FFFFFF',true);
  d.body.forEach((v,j)=>tx(s,v,76,445+j*108,1440,96,31,j===2?'#CFB67C':'#E3EADC'));
  tx(s,'GoldenStock · 24 ноября 2026',76,831,1400,32,21,'#C2D3C5');
 }
}
const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
const finalPath=path.join(out,process.env.GS_DECK_NAME||'GoldenStock-Project-Overview-2026-11-24.pptx');
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath,
 pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-bullet-geometry','--validate-heading-fit',...tableOwners.flatMap(n=>['--require-native-table-slide',String(n)])],
 requiredNativeTableOwnerSlides:tableOwners,requiredNativeChartOwnerSlides:[],fontPolicy:{basis:'design',families:['Arial']},verifyArtifactToolImport:true,receiptPath:path.join(build,path.basename(finalPath)+'.validation.json')});
console.log('Finalized '+slides.length+' slides. Rendering the final file.');
// A fresh process avoids sharing export and render WASM state.
const render=spawnSync(process.execPath,[path.join(root,'scripts/render_project_overview.mjs')],{env:process.env,stdio:'inherit'});
if(render.status!==0)throw Error('Final presentation rendering failed');
console.log(JSON.stringify({finalPath,slides:slides.length,tables:tableOwners.length},null,2));

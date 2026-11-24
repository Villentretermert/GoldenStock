// Run rendering in a fresh process, separate from export/finalizer WASM state.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {slides} from '../assets/project_overview_content.mjs';
const runtime=process.env.GS_RUNTIME_ROOT;
const {PresentationFile,FileBlob,registerPdfFontFace}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')));
for(const [weight,file]of[[400,'arial.ttf'],[700,'arialbd.ttf']])registerPdfFontFace({family:'Arial',style:'normal',weight,source:new Uint8Array(await fs.readFile(path.join(process.env.WINDIR,'Fonts',file)))});
const root=process.cwd(),build=path.join(root,'.build-overview/deck');
const finalPath=path.join(root,'deliverables',process.env.GS_DECK_NAME||'GoldenStock-Project-Overview-2026-11-24.pptx');
try{
 const imported=await PresentationFile.importPptx(await FileBlob.load(finalPath));
 console.log('Imported final file: '+imported.slides.items.length+' slides');
 for(let i=0;i<imported.slides.items.length;i++){
  const blob=await imported.export({slide:imported.slides.getItem(i),format:'png',scale:1});
  await fs.writeFile(path.join(build,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
  if(i%8===0)console.log('Rendered '+(i+1)+' / '+slides.length);
 }
 await fs.writeFile(path.join(build,'slide-index.json'),JSON.stringify(slides.map((s,i)=>({slide:i+1,title:s.title,kind:s.kind,source:s.source})),null,2));
 const narrative=['# GoldenStock: полный обзор проекта','Дата: 24 ноября 2026. Текстовое сопровождение локальной презентации на 76 слайдов.','Функциональный кандидат: 0a389bb9e30f091443a422ab2afcffdf75d96720. 32/36 DONE технически, GS-001/004/023/024 REVIEW. Реальная приёмка NO-GO.'];
 slides.forEach((s,i)=>narrative.push(`\n## ${i+1}. ${s.title}\n`,...s.body.map(v=>Array.isArray(v)?v.join(' — '):v),s.note||'',`\nИсточники: ${s.source}.`));
 await fs.writeFile(path.join(root,'docs/PROJECT_OVERVIEW_2026-11-24.md'),narrative.join('\n\n'));
 // Viewing PDF uses the inspected final PNGs; the PPTX remains editable.
 const pdf=spawnSync(path.join(root,'.venv/Scripts/python.exe'),[path.join(root,'scripts/build_project_pdf.py'),finalPath],{stdio:'inherit'});
 if(pdf.status!==0)throw Error('PDF viewing copy failed');
 console.log('Rendered all final slides and created the PDF viewing copy.');
}catch(error){console.error(error.message);process.exitCode=1;}

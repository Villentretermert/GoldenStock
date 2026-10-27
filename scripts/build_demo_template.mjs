// Synthetic contract example. No real issuer data or valuation recommendation.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(path.join(runtime,'@oai/artifact-tool/dist/artifact_tool.mjs')));
const wb=Workbook.create();const m=wb.worksheets.add('Model');const map=wb.worksheets.add('GS_Map');
m.getRange('A1:F1').merge();m.getRange('A1').values=[['GoldenStock synthetic template']];
m.getRange('A2:F2').merge();m.getRange('A2').values=[['Illustrative profit forecast in USD. No real company data.']];
m.getRange('A4:F4').merge();m.getRange('A4').values=[['This tests the template contract. Server calculation is a later step.']];
m.getRange('A6:F7').values=[['Forecast year',2026,2027,2028,2029,2030],['Profit attributable to owners',null,null,null,null,null]];
m.getRange('B7:F7').formulas=[['=$B$11*(1+$B$12)','=B7*(1+$B$12)','=C7*(1+$B$12)','=D7*(1+$B$12)','=E7*(1+$B$12)']];
m.getRange('A10:B12').values=[['Synthetic inputs','Value'],['Profit attributable to owners FY2025 (USD)',100],['Annual growth assumption',0.05]];
m.getRange('A15:F15').merge();m.getRange('A15').values=[['Blue cells are inputs. Shared structures remove input values and original notes.']];
m.getRange('A17:F17').merge();m.getRange('A17').values=[['Missing inputs must be supplied and confirmed before using this for a calculation.']];
const rows=[['key','role','cell','unit','period','definition'],
 ['profit_owners','input','B11','USD','FY2025','Profit attributable to owners of the parent'],
 ['growth','input','B12','ratio','assumption','Annual profit growth assumption'],
 ...Array.from({length:5},(_,i)=>['profit_'+(2026+i),'output',String.fromCharCode(66+i)+'7','USD','FY'+(2026+i),'Illustrative projected profit attributable to owners'])];
map.getRange('A1:F8').values=rows;
for(const s of [m,map]){s.showGridLines=false;s.getRange(s===m?'A1:F18':'A1:F8').format.font={name:'Arial',size:11,color:'#193B30'};}
m.getRange('A1:F1').format.font={name:'Arial',size:16,bold:true,color:'#193B30'};
m.getRange('A:A').format.columnWidth=43;m.getRange('B:F').format.columnWidth=18;
m.getRange('A1:F18').format.rowHeight=28;m.getRange('A11').format.wrapText=true;m.getRange('A11:F11').format.rowHeight=42;
for(const range of ['A6:F6','A10:B10'])m.getRange(range).format={fill:'#285641',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'}};
m.getRange('B11:B12').format={fill:'#E8F0FF',font:{name:'Arial',size:11,color:'#0000FF'}};
m.getRange('B7:F7').format.font={name:'Arial',size:11,color:'#000000',bold:true};
m.getRange('B7:F7').setNumberFormat('#,##0.00;(#,##0.00);"-"');m.getRange('B11').setNumberFormat('#,##0.00');m.getRange('B12').setNumberFormat('0.0%');
map.getRange('A1:F1').format={fill:'#285641',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'}};
map.getRange('A:E').format.columnWidth=22;map.getRange('F:F').format.columnWidth=58;map.getRange('A1:F8').format.rowHeight=38;map.getRange('A1:F8').format.wrapText=true;
wb.recalculate();
const vals=m.getRange('B7:F7').values[0];
for(let i=0;i<5;i++)if(Math.abs(vals[i]-100*1.05**(i+1))>1e-8)throw Error('Forecast dependency mismatch');
m.getRange('B12').values=[[0]];if(m.getRange('F7').values[0][0]!==100)throw Error('Zero input mishandled');
m.getRange('B12').values=[[0.05]];wb.recalculate();
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:10}})).ndjson);
await fs.mkdir('src/goldenstock/assets',{recursive:true});await fs.mkdir('.build-template-demo',{recursive:true});
await(await SpreadsheetFile.exportXlsx(wb)).save('src/goldenstock/assets/demo-template.xlsx');
for(const s of ['Model','GS_Map']){const img=await wb.render({sheetName:s,range:s==='Model'?'A1:F18':'A1:F8',scale:1,format:'png'});await fs.writeFile('.build-template-demo/'+s+'.png',new Uint8Array(await img.arrayBuffer()));}
console.log('Demo exported, recalculation and zero-growth boundary checked.');

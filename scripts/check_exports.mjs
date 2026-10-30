// Independent spreadsheet recalculation and local rendering of synthetic report fixtures.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {FileBlob,SpreadsheetFile,PresentationFile}=await import(pathToFileURL(path.join(runtime,'@oai/artifact-tool/dist/artifact_tool.mjs')));
const root='.build-export-fixtures';
const output=path.join(root,'rendered');await fs.mkdir(output,{recursive:true});
for(const method of ['pe','pb','ddm','fcfe']){
  const saved=JSON.parse(await fs.readFile(path.join(root,method+'.json'),'utf8'));
  const book=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(root,method+'.xlsx')));
  book.recalculate();
  const summary=book.worksheets.getItem('Summary'), val=book.worksheets.getItem('Val_base');
  const expected=Number(saved.result.scenarios.base.values.per_share.value);
  const near=(actual,want,label)=>{if(typeof actual!=='number'||Math.abs(actual-want)>1e-7*Math.max(1,Math.abs(want)))throw Error(method+' '+label+': '+actual+' != '+want);};
  near(summary.getRange('B8').values[0][0],expected,'base result after recalculation');
  const sens=book.worksheets.getItem('Sensitivity');
  for(const [i,p] of saved.result.scenarios.base.sensitivity.entries())if(p.per_share)near(sens.getRange('D'+(8+i)).values[0][0],Number(p.per_share.value),'sensitivity '+i);
  val.getRange('C8').values=[[20]];book.recalculate();near(summary.getRange('B8').values[0][0],expected/2,'changed shares');
  val.getRange('C8').values=[[0]];book.recalculate();if(val.getRange('B3').values[0][0]!==false)throw Error('zero shares not blocked');
  val.getRange('C8').values=[[null]];book.recalculate();if(val.getRange('B3').values[0][0]!==false)throw Error('missing shares not blocked');
  val.getRange('C8').values=[[10]];book.recalculate();near(summary.getRange('B8').values[0][0],expected,'restored shares');
  if(['ddm','fcfe'].includes(method)){
    val.getRange('C14').values=[[.12]];book.recalculate();
    near(sens.getRange('B12').values[0][0],.12,'sensitivity center follows cost of equity');
    near(sens.getRange('D12').values[0][0],summary.getRange('B8').values[0][0],'sensitivity center matches changed base');
    val.getRange('C14').values=[[.1]];book.recalculate();
  }
  const scan=await book.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!',options:{useRegex:true,maxResults:5}});
  await fs.writeFile(path.join(output,method+'-formula-scan.json'),scan.ndjson);
  if(method==='ddm')for(const name of ['Summary','Calc_base','Val_base','Sensitivity','Evidence']){
    const range=name==='Summary'?'A1:E27':name==='Evidence'?'A1:E18':'A1:E20';
    const img=await book.render({sheetName:name,range,scale:1,format:'png'});
    await fs.writeFile(path.join(output,'xlsx-'+name+'.png'),new Uint8Array(await img.arrayBuffer()));
  }
  console.log(method+': base, all sensitivity points, edited shares, zero/missing boundaries passed');
  if(method==='ddm'){
    const deck=await PresentationFile.importPptx(await FileBlob.load(path.join(root,method+'.pptx')));
    for(let i=0;i<deck.slides.items.length;i++){
      const img=await deck.export({slide:deck.slides.getItem(i),format:'png',scale:1});
      await fs.writeFile(path.join(output,'pptx-'+String(i+1).padStart(2,'0')+'.png'),new Uint8Array(await img.arrayBuffer()));
    }
    console.log('Rendered '+deck.slides.items.length+' DDM slides');
  }
}
const linked=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(root,'linked.xlsx')));
linked.recalculate();
const linkedSummary=linked.worksheets.getItem('Summary');
if(linkedSummary.getRange('B8:B10').values.flat().join(',')!=='90,190,40')throw Error('Linked scenarios mismatch');
linked.worksheets.getItem('Calc_base').getRange('C8').values=[[300]];linked.recalculate();
if(linkedSummary.getRange('B8').values[0][0]!==290)throw Error('Source input did not propagate to valuation');
if(linkedSummary.getRange('B9').values[0][0]!==190)throw Error('Scenario cross-contamination');
linkedSummary.getRange('B14').values=[[100]];linked.recalculate();
if(Math.abs(linkedSummary.getRange('D8').values[0][0]-1.9)>1e-10)throw Error('Quote change did not propagate');
const boundary=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(root,'boundary.xlsx')));
boundary.recalculate();
if(boundary.worksheets.getItem('Sensitivity').getRange('D8').values[0][0]!=='Blocked')throw Error('Invalid sensitivity not blocked');
console.log('Three scenarios, source binding, quote change and invalid sensitivity passed');

// Check the finished offline player without opening the application or its database.
const fs=require('node:fs'),path=require('node:path');
const {pathToFileURL}=require('node:url');
const {createRequire}=require('node:module');
const req=createRequire(path.join(process.env.GS_RUNTIME_ROOT,'node/node_modules/playwright/package.json'));
const {chromium}=req('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route(/^https?:/,route=>route.abort());
  await page.goto(pathToFileURL(path.resolve('deliverables/GoldenStock-Project-Demo-2026-11-24.html')).href);
  await page.waitForFunction(()=>document.querySelector('video').readyState>=1);
  const metadata=await page.locator('video').evaluate(v=>({duration:v.duration,width:v.videoWidth,height:v.videoHeight}));
  if(metadata.duration<420||metadata.duration>421)throw Error('Wrong media duration');
  const buttons=page.locator('button[data-time]'),count=await buttons.count();
  if(count!==26)throw Error('Missing chapters');
  for(let i=0;i<count;i++){
   const button=buttons.nth(i),time=Number(await button.getAttribute('data-time'));
   await button.click();
   await page.waitForFunction(t=>{const v=document.querySelector('video');return !v.paused&&!v.seeking&&Math.abs(v.currentTime-t)<3;},time);
   await page.locator('video').evaluate(v=>v.pause());
  }
  await buttons.first().click();
  await page.waitForTimeout(800);
  await page.locator('video').evaluate(v=>v.pause());
  await page.screenshot({path:'.build-overview/demo-player.png',fullPage:true});
  if(errors.length)throw Error(errors.join('\n'));
  fs.writeFileSync('.build-overview/player-validation.json',JSON.stringify({metadata,chapters:count,all_chapters_played:true,errors},null,2));
  console.log(JSON.stringify({metadata,chapters:count,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});

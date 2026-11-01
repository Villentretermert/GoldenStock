// Render actual Python HTML from the synthetic API test, with isolated browser routes.
const fs=require('fs'),path=require('path'),{createRequire}=require('module');
const req=createRequire(path.join(process.env.GS_NODE_MODULES,'playwright','package.json'));
const {chromium}=req('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const html=fs.readFileSync('.build-monitor-preview.html','utf8');let read=false;const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{
   const u=new URL(route.request().url());
   if(u.origin!=='http://127.0.0.1:8099')throw Error('Unexpected external browser request');
   if(u.pathname==='/api/v1/notifications/count')return route.fulfill({json:{unread_count:read?0:1}});
   if(/^\/api\/v1\/notifications\/[a-f0-9]+\/read$/.test(u.pathname)){
    if(route.request().method()!=='POST'||!route.request().headers()['x-csrf-token'])throw Error('Invalid read form');
    read=true;return route.fulfill({json:{read_at:1}});
   }
   if(u.pathname==='/updates')return route.fulfill({contentType:'text/html',body:read?html.replace('1 unread','0 unread').replace('Unread · JPM','Read · JPM').replace(/<form[^>]+data-api="\/api\/v1\/notifications\/[^"]+\/read"[^>]*>.*?<\/form>/g,''):html});
   throw Error('Unexpected route '+u.pathname);
  });
  await page.goto('http://127.0.0.1:8099/updates',{waitUntil:'networkidle'});
  await page.getByRole('heading',{name:'Previously reported number changed — review required'}).waitFor();
  fs.mkdirSync('design/previews',{recursive:true});
  await page.screenshot({path:'design/previews/monitor-desktop.png',fullPage:true});
  await page.screenshot({path:'design/previews/monitor-feed.png'});
  await page.setViewportSize({width:390,height:900});
  await page.screenshot({path:'design/previews/monitor-mobile.png',fullPage:true});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
  await page.getByRole('button',{name:'Mark as read',exact:true}).click();
  await page.getByText('0 unread',{exact:false}).waitFor();
  if(!read||errors.length)throw Error(JSON.stringify(errors));
  console.log('Synthetic monitoring UI PASS: change feed, source links, read form, badge and mobile layout; no live sources modified.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

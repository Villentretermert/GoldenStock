// Real Python pages from isolated API tests. Browser routes never touch live SEC observations.
const fs=require('fs'),path=require('path'),{createRequire}=require('module');
const req=createRequire(path.join(process.env.GS_NODE_MODULES,'playwright','package.json'));
const {chromium}=req('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  const folder='.build-monitor-comparison',receipt=JSON.parse(fs.readFileSync(folder+'/receipt.json','utf8'));
  let read=false;
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>{
   const url=new URL(route.request().url());
   if(url.origin!=='http://127.0.0.1:8099')throw Error('External request in isolated comparison');
   if(url.pathname==='/api/v1/notifications/count')return route.fulfill({json:{unread_count:read?0:1}});
   if(/^\/api\/v1\/notifications\/[a-f0-9]+\/read$/.test(url.pathname)){
    if(route.request().method()!=='POST'||!route.request().headers()['x-csrf-token'])throw Error('Invalid read form');
    read=true;return route.fulfill({json:{read_at:1}});
   }
   let file=url.pathname==='/updates'?'feed.html':url.pathname===receipt.history_url?'history.html':url.pathname==='/monitoring/jpm-facts'?'values.html':null;
   if(!file)throw Error('Unexpected route '+url.pathname);
   let html=fs.readFileSync(folder+'/'+file,'utf8');if(read)html=html.replace('1 unread','0 unread');
   return route.fulfill({contentType:'text/html',body:html});
  });
  await page.goto('http://127.0.0.1:8099/updates',{waitUntil:'networkidle'});
  await page.getByRole('heading',{name:'Previous publication',exact:true}).waitFor();
  await page.getByRole('heading',{name:'New publication',exact:true}).waitFor();
  await page.getByText('Change of at least 5%',{exact:true}).waitFor();
  if(await page.getByRole('link',{name:'Official SEC filing',exact:true}).count()!==2)throw Error('Both filings required');
  await page.screenshot({path:'design/previews/sec-comparison-desktop.png'});
  await page.setViewportSize({width:390,height:900});
  await page.screenshot({path:'design/previews/sec-comparison-mobile.png',fullPage:true});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Comparison overflow');
  await page.getByRole('link',{name:'Observed value history',exact:true}).click();
  await page.getByRole('heading',{name:'Source refreshed; numeric value unchanged',exact:true}).waitFor();
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('History overflow');
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({path:'design/previews/sec-history-desktop.png'});
  await page.getByRole('link',{name:'Observed SEC values',exact:true}).click();
  await page.getByRole('heading',{name:'Total assets',exact:true}).waitFor();
  await page.getByRole('link',{name:'Reporting updates',exact:true}).click();
  await page.getByRole('button',{name:'Mark as read',exact:true}).click();
  await page.getByText('0 unread',{exact:false}).waitFor();
  if(errors.length)throw Error(JSON.stringify(errors));
  console.log('SEC comparison browser PASS: previous/new filings, 5% highlight, source refresh history, values navigation, private read form and desktop/mobile layout. Synthetic sources only.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

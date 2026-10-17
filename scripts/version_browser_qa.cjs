const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const [base,run,conversation,directory,mode='versions']=process.argv.slice(2);
(async()=>{
 fs.mkdirSync(directory,{recursive:true});
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  page.setDefaultTimeout(10000);
  const writes=[],errors=[];
  page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method()))writes.push(r.url());});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`${base}/workspace?run=${run}&conversation=${conversation}&version=1`);
  await page.getByRole('heading',{name:/高收益玩家更常做了什麼？/}).waitFor();
  if(mode==='pending')await page.getByText('查看分析進度與結果 · 處理中',{exact:true}).waitFor();
  for(const version of mode==='pending'?[1]:[2,1]){
   await page.getByLabel(`檢視報告版本 v${mode==='pending'?1:version===2?1:2}`,{exact:true}).click();
   await page.locator(`.branch-list a[href*="run=${run}"]`).first().waitFor();
   await page.screenshot({path:`${directory}/picker-${version}.png`});
   if(mode==='versions'){
    await page.locator(`.branch-list a[href*="version=${version}"]`).click();
    await page.waitForURL(url=>url.searchParams.get('version')===String(version));
   }else await page.getByLabel('檢視報告版本 v1',{exact:true}).click();
   await page.getByRole('tab',{name:'候選事件',exact:true}).click();
   await page.getByRole('button',{name:/^優先結果/}).waitFor();
   await page.getByRole('combobox',{name:/^排序/}).selectOption('coverage');
   await page.getByRole('tab',{name:'圖表',exact:true}).click();
   const chart=page.locator('.chart-section svg').first();
   await chart.waitFor();await chart.click({position:{x:100,y:100}});
   assert.equal(await page.getByRole('link',{name:'匯出',exact:true}).getAttribute('href'),`/api/runs/${run}/reports/${version}/html`);
   assert.equal(new URL(page.url()).searchParams.get('run'),run);
   if(mode==='pending')await page.getByText('查看分析進度與結果 · 處理中',{exact:true}).waitFor();
   await page.screenshot({path:`${directory}/results-${version}.png`});
   await page.reload();await page.locator('.chart-section svg').first().waitFor();
   assert.equal(new URL(page.url()).searchParams.get('version'),String(version));
   assert((await page.locator('.context-line').textContent()).includes(`第 ${version} 版`));
  }
  await page.setViewportSize({width:390,height:844});
  await page.getByLabel('檢視報告版本 v1',{exact:true}).click();
  await page.locator('.branch-list a').first().waitFor();
  assert((await page.evaluate(()=>document.documentElement.scrollWidth))<=390);
  await page.screenshot({path:`${directory}/picker-mobile.png`});
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({mode,readOnly:true,sortAndChart:true,refresh:true,versionContext:true,pageErrors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

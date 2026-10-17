const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const [base,dataset,finding,dir,mode]=process.argv.slice(2);
(async()=>{
 fs.mkdirSync(dir,{recursive:true});const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900}});const writes=[],errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')writes.push(r.url());});
  await page.goto(`${base}/upload?dataset=${dataset}`);
  const checkbox=page.locator(`input[type=checkbox][value="${finding}"]`);
  await checkbox.waitFor();assert.equal(await checkbox.isChecked(),false);
  await checkbox.check();await page.getByRole('button',{name:'再次檢查先前的事件',exact:true}).waitFor();
  await page.reload();await checkbox.waitFor();assert.equal(await checkbox.isChecked(),true);
  await page.getByRole('button',{name:'再次檢查先前的事件',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:`${dir}/finding-selector.png`});
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'再次檢查先前的事件',exact:true}).scrollIntoViewIfNeeded();
  assert((await page.evaluate(()=>document.documentElement.scrollWidth))<=390);
  await page.screenshot({path:`${dir}/finding-selector-mobile.png`});
  await page.getByRole('button',{name:'清除重驗選擇',exact:true}).click();
  await page.getByRole('button',{name:'開始分析',exact:true}).waitFor();
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  if(mode==='submit'){
   await checkbox.check();
   const responsePromise=page.waitForResponse(r=>r.url().endsWith(`/datasets/${dataset}/finding-recheck`)&&r.request().method()==='POST');
   await page.getByRole('button',{name:'再次檢查先前的事件',exact:true}).click();
   const response=await responsePromise;assert.equal(response.status(),202);
   const queued=await response.json(),request=response.request();
   assert.deepEqual(request.postDataJSON().finding_ids,[finding]);
   await page.getByRole('link',{name:'查看分析進度',exact:true}).click();
   await page.getByRole('link',{name:'開啟分析工作區',exact:true}).waitFor({timeout:90000});
   await page.getByRole('link',{name:'開啟分析工作區',exact:true}).click();
   const section=page.getByRole('region',{name:'固定舊規則重驗',exact:true});
   await section.waitFor();assert.match(await section.innerText(),/僅探索性結果/);
   const sourceDetails=section.locator('details').filter({has:page.getByText('這項檢查的來源識別資料',{exact:true})});
   assert.match(await sourceDetails.textContent(),new RegExp(finding));
   assert.match(await section.locator('h4').first().innerText(),/小時內/);
   await section.scrollIntoViewIfNeeded();
   assert((await page.evaluate(()=>document.documentElement.scrollWidth))<=390);
   await page.screenshot({path:`${dir}/finding-recheck-mobile.png`});
   await page.setViewportSize({width:1440,height:900});await page.reload();await section.waitFor();
   assert.equal(new URL(page.url()).searchParams.get('run'),queued.run_id);
   await section.scrollIntoViewIfNeeded();await page.screenshot({path:`${dir}/finding-recheck-desktop.png`});
   for(const format of ['json','html','csv']){
    const exported=await page.request.get(`${base}/api/runs/${queued.run_id}/reports/1/${format}`);
    assert.equal(exported.status(),200);
    if(format==='json')assert.equal((await exported.json()).summary.finding_recheck.sources[0].finding_id,finding);
    if(format==='html')assert.match(await exported.text(),new RegExp(finding));
   }
   assert.equal(writes.filter(url=>url.endsWith('/finding-recheck')).length,1);
   assert.deepEqual(errors,[]);assert.equal(await page.getByRole('alert').count(),0);
   console.log(JSON.stringify({queued,body:request.postDataJSON(),key:request.headers()['idempotency-key'],browserSubmission:true,reportRefresh:true,exports:true}));
  }
  console.log(JSON.stringify({synthetic:true,explicitSelection:true,draftRefresh:true,clearReturnsToSearch:true,selectionBeforeSubmitReadOnly:true}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const [mode,base,run,dir]=process.argv.slice(2);
(async()=>{
 fs.mkdirSync(dir,{recursive:true});
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:900},acceptDownloads:true});
  const page=await context.newPage(),errors=[],network=[];
  page.on('pageerror',e=>errors.push(e.message));
  if(mode==='download'){
   await page.goto(`${base}/workspace?run=${run}`);
   await page.getByLabel('更多匯出格式').click();
   for(const format of ['html','json','csv']){
    const link=page.getByRole('link',{name:`下載 ${format.toUpperCase()}`,exact:true});
    assert.equal(await link.getAttribute('href'),`/api/runs/${run}/reports/1/${format}`);
    const waiting=page.waitForEvent('download');await link.click();const download=await waiting;
    assert.equal(await download.failure(),null);await download.saveAs(path.join(dir,`report.${format}`));
   }
   const downloadedReport=JSON.parse(fs.readFileSync(path.join(dir,'report.json'),'utf8'));
   assert.equal(downloadedReport.run_id,run);
   if(downloadedReport.summary.segment){
    await page.getByLabel('更多匯出格式').click();
    const segment=downloadedReport.summary.segment;
    const table=page.getByRole('region',{name:'分群事件比較',exact:true});
    if(segment.candidates.length===0){
     await page.getByText('這次沒有可比較的事件條件。請查看上述資料限制。',{exact:true}).waitFor();
     assert.equal(await table.count(),0);
     assert(segment.reasons.includes('NO_PARENT_CANDIDATES'));
    }else await table.waitFor();
    const rows=await table.locator('tbody tr').evaluateAll(elements=>elements.map(row=>({id:row.dataset.segmentCandidate,split:row.dataset.split,text:row.innerText,values:[...row.querySelectorAll('[data-value]')].map(el=>Number(el.dataset.value))})));
    assert.equal(rows.length,segment.candidates.length);
    for(let i=0;i<rows.length;i++){
     const source=segment.candidates[i];assert.equal(rows[i].id,source.candidate_id);assert.equal(rows[i].split,source.split);
     assert.deepEqual(rows[i].values,[source.metrics?.groups.triggered.users,source.users,source.metrics?.coverage,source.metrics?.groups.triggered.arpu_usd,source.metrics?.delay_seconds.median].filter(v=>v!=null));
     assert(!rows[i].text.includes(source.candidate_id));assert.match(rows[i].text,/小時內/);
    }
    for(const width of [1440,390]){await page.setViewportSize({width,height:900});if(segment.candidates.length)await table.scrollIntoViewIfNeeded();assert((await page.evaluate(()=>document.documentElement.scrollWidth))<=width);await page.screenshot({path:path.join(dir,`segment-web-${width}.png`)});}
   }
   await page.reload();await page.getByLabel('更多匯出格式').waitFor();
  }else{
   const report=JSON.parse(fs.readFileSync(path.join(dir,'report.json'),'utf8'));
   await context.setOffline(true);
   page.on('request',request=>{if(/^https?:/.test(request.url()))network.push(request.url());});
   await page.goto(pathToFileURL(path.join(dir,'report.html')).href);
   assert.equal(await page.locator('script,iframe,img[src^="http"],link[rel="stylesheet"]').count(),0);
   await page.locator('details').evaluateAll(elements=>elements.forEach(element=>element.open=true));
   assert.match(await page.locator('body').innerText(),new RegExp(run));
   for(const candidate of report.candidates){
    const article=page.locator(`[id="candidate-${candidate.candidate_id}"]`);
    assert.equal(await article.count(),1);
    assert.match(await article.innerText(),new RegExp(candidate.event_spec.event_name));
    for(const group of Object.values(candidate.metrics?.groups||{})){
     for(const value of [group.users,group.arpu_usd])if(value!==null&&value!==undefined)
      assert(await article.locator(`[data-value="${value}"]`).count()>0,`Missing actual metric ${value}`);
    }
   }
   for(const id of ['comparison','evidence','sensitivity','overlap','remaining','audit'])assert.equal(await page.locator(`#${id}`).count(),1);
   async function numericTable(caption,expected){
    const rows=page.getByRole('table',{name:caption,exact:true}).locator('tbody tr');
    const actual=await rows.evaluateAll(elements=>elements.map(row=>({
     values:Array.from(row.querySelectorAll('[data-value]')).map(e=>Number(e.dataset.value)),
     unknown:Array.from(row.querySelectorAll('span.muted')).filter(e=>e.textContent==='未知').length})));
    assert.equal(actual.length,expected.length,caption);
    for(let i=0;i<expected.length;i++){
     assert.deepEqual(actual[i].values,
      expected[i].filter(value=>value!==null&&value!==undefined),`${caption} row ${i}`);
     assert.equal(actual[i].unknown,expected[i].filter(value=>value===null||value===undefined).length);
    }
   }
   const diagnostics=report.diagnostics;
   await numericTable('提高要求後，人數與收益如何變化？',(diagnostics.sensitivity?.points||[]).map(p=>
    [p.threshold,p.triggered_users,p.cohort_users,p.coverage,p.triggered_arpu_usd,p.triggered_revenue_p99_usd]));
   await numericTable('不同條件選中的是同一批人嗎？',(diagnostics.overlap?.pairs||[]).filter(p=>p.a!==p.b).map(p=>
    [p.a_users,p.b_users,p.intersection,p.union,p.jaccard,p.fraction_a_in_b,p.fraction_b_in_a]));
   await numericTable('符合條件之後的平均廣告收益',(diagnostics.landmark?.post_trigger||[]).map(p=>[p.users,p.arpu_usd,p.unknown_revenue_users]));
   await numericTable('在相同時間點比較剩餘收益',(diagnostics.landmark?.landmarks||[]).map(p=>
    [p.landmark_hours,p.triggered.users,p.triggered.arpu_usd,p.untriggered.users,p.untriggered.arpu_usd]));
   if(report.summary.segment){
    await numericTable('分群分母與收益',Object.values(report.summary.segment.cohorts).map(p=>[p.users,p.revenue_usd,p.arpu_usd]));
    await numericTable('分群事件比較',report.summary.segment.candidates.map(p=>[p.metrics?.groups.triggered.users,p.users,p.metrics?.coverage,p.metrics?.groups.triggered.arpu_usd,p.metrics?.delay_seconds.median]));
    assert.match(await page.locator('body').innerText(),/原始候選完整打點規格/);
   }
   for(const href of await page.locator('a[href]').evaluateAll(elements=>elements.map(e=>e.getAttribute('href')))){
    assert(href.startsWith('#'),'Offline report contains an external navigation dependency');
    assert.equal(await page.locator(`[id="${href.slice(1)}"]`).count(),1);
   }
   await page.locator('details').evaluateAll(elements=>elements.forEach(element=>element.open=false));
   await page.screenshot({path:path.join(dir,'offline-desktop.png')});
   await page.setViewportSize({width:390,height:844});await page.reload();
   assert((await page.evaluate(()=>document.documentElement.scrollWidth))<=390);
   await page.screenshot({path:path.join(dir,'offline-mobile.png')});
   assert.deepEqual(network,[]);
  }
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({mode,run,synthetic:true,offline:mode!=='download',networkRequests:network.length}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

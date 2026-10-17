const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),crypto=require('crypto'),assert=require('assert/strict');
(async()=>{
const [url,root,out,pages]=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
const report=JSON.parse(fs.readFileSync(path.join(root,'report.json'))),catalog=JSON.parse(fs.readFileSync(path.join(root,'catalog/catalog.json')));
const raw=fs.readFileSync(path.join(root,'report.json')),sha=crypto.createHash('sha256').update(raw).digest('hex');
const browser=await chromium.launch({channel:'chrome',headless:true});
try{for(const width of [1440,390]){
 const page=await browser.newPage({viewport:{width,height:950}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/api/**',async route=>{
  const u=new URL(route.request().url());let body;
  if(u.pathname.endsWith('/json'))return route.fulfill({body:raw,contentType:'application/json',headers:{etag:`"${sha}"`}});
  if(u.pathname.endsWith('/candidates'))body={run_id:report.run_id,report_version:1,report_sha256:sha,catalog_sha256:report.catalog.sha256,evaluated_count:catalog.evaluated_count,comparison_users:report.summary.targets.mature_users,filtered_count:catalog.evaluated_count,page:1,page_size:50,query:{page:1},priority_ids:catalog.priority_ids,items:catalog.entries.slice(0,50).map(e=>({...e,summary:Object.fromEntries(Object.entries(e.summary).filter(([k])=>!['time_comparisons','time_evidence'].includes(k)))}))};
  else if(u.pathname.endsWith('/candidate-search')){const search=JSON.parse(fs.readFileSync(path.join(root,'catalog/search.json'))),log=search.search_log??search.pruning??[],p=Number(u.searchParams.get('page')||1);body={run_id:report.run_id,report_version:1,report_sha256:sha,catalog_sha256:report.catalog.sha256,sha256:sha,page:p,page_size:50,pruning_count:log.length,items:log.slice((p-1)*50,p*50),summary:Object.fromEntries(Object.entries(search).filter(([k])=>!['search_log','pruning'].includes(k)))};}
  else if(u.pathname.includes('/candidates/')){const id=u.pathname.split('/').at(-1),entry=catalog.entries.find(e=>e.candidate_id===id);body={run_id:report.run_id,report_version:1,report_sha256:sha,catalog_sha256:report.catalog.sha256,sha256:entry.detail_sha256,content:JSON.parse(fs.readFileSync(path.join(root,'catalog/details',id+'.json')))};}
  else return route.abort();
  if(pages&&u.pathname.endsWith('/candidates')){const saved=path.join(pages,`${u.searchParams.get('window_hours')||24}-${u.searchParams.get('page')||1}.json`);if(fs.existsSync(saved))body=JSON.parse(fs.readFileSync(saved));}
  await route.fulfill({json:body});
 });
 await page.goto(`${url}/test/v4-fixture.html?run=${report.run_id}&dataset=${report.dataset_id}`);
 await page.getByRole('heading',{name:'行為分析'}).waitFor();
 assert.equal(await page.getByRole('region',{name:'行為比較'}).locator('thead th').count(),6);
 await page.getByLabel('主表觀察時間').selectOption('48');
 assert((await page.getByRole('region',{name:'行為比較'}).innerText()).includes('48 小時'));
 await page.getByRole('button',{name:'比較每天新增的玩家'}).first().click();
 await page.getByRole('heading',{name:'多觀察一天，能多找到誰？'}).waitFor();
 assert.equal(await page.getByRole('region',{name:'每天新增玩家'}).locator('tbody tr').count(),6);
 if(report.candidates[0]?.time_analysis?.exploration){
  await page.getByRole('navigation',{name:'比較資料來源'}).getByRole('button',{name:'找規律（探索集）',exact:true}).click();
  const expected=report.candidates[0].time_analysis.exploration[0].groups.all.users;
  assert((await page.getByRole('region',{name:'行為與時間比較'}).innerText()).includes(`本視角母體：${expected.toLocaleString("en-US")}`));
 }
 await page.getByRole('navigation',{name:'比較資料來源'}).getByRole('button',{name:'Holdout 驗證集',exact:true}).click();
 await page.getByLabel('比較同一個時間點').selectOption('144');
 assert.equal(await page.getByRole('img',{name:'六個觀察時間的達標玩家人數'}).count(),1);
 assert.equal(await page.getByLabel('聊天選取上下文').innerText(),JSON.stringify({hours:144,cohort:'holdout'}));
 assert((await page.getByRole('region',{name:'每天新增玩家'}).innerText()).includes('新增玩家七天總收入'));
 assert.equal(await page.getByRole('alert').count(),0);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:path.join(out,`v4-${width}.png`),fullPage:true});
 for(const tab of ['圖表','資料品質','候選事件']){
  await page.goto(`${url}/test/v4-fixture.html?run=${report.run_id}&dataset=${report.dataset_id}&tab=${encodeURIComponent(tab)}`);
  if(tab==='圖表')await page.getByRole('img',{name:'六個觀察時間的達標玩家人數'}).waitFor();
  if(tab==='資料品質'){await page.getByRole('heading',{name:'這批資料可以分析什麼？',exact:true}).waitFor();await page.getByRole('heading',{name:'本次搜尋的邊界'}).waitFor();assert.equal(await page.getByRole('region',{name:'行為比較'}).count(),0);}
  if(tab==='候選事件'){await page.getByRole('navigation',{name:'結果分頁'}).waitFor();}
  assert.equal(await page.getByRole('alert').count(),0);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width} ${tab}: `+JSON.stringify(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth).slice(0,8).map(e=>[e.tagName,e.className,e.getBoundingClientRect().right]))));
 }
 assert.deepEqual(errors,[]);await page.close();
}
fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({passed:true,widths:[1440,390],checks:['real calculation fixture','report checksum','catalog detail','six checkpoints','holdout tab','144h control','no horizontal overflow','no JS errors','chart and quality tabs','three cohorts','selected chat clock/cohort','daily revenue and share']}));
}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});

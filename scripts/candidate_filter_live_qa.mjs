import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const base='http://127.0.0.1:5183',run='6d92a161-3ff0-4eaa-8305-6736fe1d1f13';
const reportUrl=`${base}/api/runs/${run}/reports/1/json`,listPath=`/api/runs/${run}/reports/1/candidates`;
const digest=async()=>createHash('sha256').update(Buffer.from(await(await fetch(reportUrl)).arrayBuffer())).digest('hex');
const before=await digest(),browser=await chromium.launch({channel:'chrome',headless:true});
try{for(const width of [1440,390]){
 const page=await browser.newPage({viewport:{width,height:900}}),writes=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(`${base}/workspace?run=${run}`);await page.getByRole('tab',{name:'候選事件',exact:true}).click();
 await page.getByRole('button',{name:'全部結果（1086）',exact:true}).click();
 const catalog=page.getByRole('region',{name:'全部候選結果',exact:true});
 await catalog.getByText('本次評估 1086 項；符合篩選 1086 項。',{exact:true}).waitFor();
 page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))writes.push({method:r.method(),url:r.url()});});
 let cases=0;
 for(const [label,param,values] of [
  ['起點後窗口','window_hours',['1','3','6','12','24','48','72','96','120','144','168']],
  ['條件類型','family',['atom','compound','sequence']],
  ['廣告格式','ad_format',['all','rewarded','interstitial','never-observed']],
  ['證據','evidence_status',['historically_validated','exploratory','insufficient_data']],
  ['比較角色','role',['unselected','價值差較大','覆蓋較廣','達標較快']],
  ['排序','sort',['difference_usd','coverage','p90_seconds','candidate_id']],
 ]){
  for(const value of values){
   console.log(JSON.stringify({width,param,value}));
   const pending=page.waitForResponse(r=>new URL(r.url()).pathname===listPath&&new URL(r.url()).searchParams.get(param)===value);
   page.once('request',r=>console.log('request '+r.url()));
   const control=param==='ad_format'?catalog.locator('.catalog-filters input'):catalog.locator('.catalog-filters select').nth(['window_hours','family','evidence_status','role','sort'].indexOf(param));
   if(param==='ad_format')await control.fill(value);else await control.selectOption(value);
   const response=await pending;assert.equal(response.status(),200);const expected=await response.json();
   await catalog.getByText(`本次評估 1086 項；符合篩選 ${expected.filtered_count} 項。`,{exact:true}).waitFor();
   await page.waitForFunction(({ids})=>JSON.stringify([...document.querySelectorAll('.candidate-catalog [data-candidate-id]')].map(n=>n.dataset.candidateId))===JSON.stringify(ids),{ids:expected.items.map(e=>e.candidate_id)});
   const exported=await catalog.locator('a').filter({hasText:'JSON'}).last().getAttribute('href');
   assert.equal(new URL(exported,base).searchParams.get(param),value);cases++;
  }
  const control=param==='ad_format'?catalog.locator('.catalog-filters input'):catalog.locator('.catalog-filters select').nth(['window_hours','family','evidence_status','role','sort'].indexOf(param));
  if(param==='ad_format')await control.fill('');else if(param!=='sort')await control.selectOption('');
 }
 assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);console.log(JSON.stringify({width,cases,writes,errors}));await page.close();
}}finally{await browser.close();}
assert.equal(await digest(),before);console.log('Parent report SHA unchanged');

import {chromium} from 'playwright';
import assert from 'node:assert/strict';
const run=process.argv[2],base='http://127.0.0.1:5183';
assert(run,'Pass a completed positive V2 run ID');
const response=await fetch(`${base}/api/runs/${run}/reports/1/json`);assert.equal(response.status,200);
const report=await response.json();assert.equal(report.schema_version,'2.0');assert(report.candidates.length>0);
const browser=await chromium.launch({channel:'chrome',headless:true});
try{for(const width of [1440,390]){
 const page=await browser.newPage({viewport:{width,height:900}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));await page.goto(`${base}/workspace?run=${run}`);
 await page.getByRole('tab',{name:'候選事件',exact:true}).click();
 const table=page.getByRole('region',{name:'優先候選完整比較',exact:true});await table.waitFor();
 assert.equal(await table.locator('tbody tr').count(),report.candidates.length);
 for(const candidate of report.candidates){
   const row=table.locator(`[data-candidate-id="${candidate.candidate_id}"]`);
   const observed=await row.locator('[data-value]').evaluateAll(nodes=>nodes.map(n=>Number(n.getAttribute('data-value'))));
   const m=candidate.metrics;
   const expected=[m?.groups.triggered.users,m?.groups.untriggered.users,m?.coverage,m?.groups.triggered.arpu_usd,
     m?.groups.untriggered.arpu_usd,m?.comparisons.triggered_minus_untriggered,m?.delay_seconds.median,m?.delay_seconds.p90].filter(v=>typeof v==='number');
   assert.deepEqual(observed,expected);
   assert.match(await row.innerText(),new RegExp(candidate.selection_evidence.role));
 }
 for(const sort of ['coverage','revenue','speed','original']){
   await page.locator('.report-panel select').selectOption(sort);
   const expected=report.candidates.slice();
   const metric=c=>sort==='coverage'?c.metrics?.coverage:sort==='speed'?c.metrics?.delay_seconds.p90:c.metrics?.comparisons.triggered_minus_untriggered;
   if(sort!=='original')expected.sort((a,b)=>{const x=metric(a),y=metric(b),tie=a.candidate_id.localeCompare(b.candidate_id);return x==null?(y==null?tie:1):y==null?-1:(sort==='speed'?x-y:y-x)||tie;});
   assert.deepEqual(await table.locator('tbody tr').evaluateAll(nodes=>nodes.map(n=>n.dataset.candidateId)),expected.map(c=>c.candidate_id));
 }
 await table.locator('tbody button').first().click();
 const id=report.candidates[0].candidate_id;
 await page.waitForFunction(id=>document.activeElement?.getAttribute('data-selected-candidate')===id,id);
 await page.screenshot({path:`evidence/CV04-priority-${width}.png`});
 await page.getByRole('button',{name:`全部結果（${report.catalog.evaluated_count}）`,exact:true}).click();
 const catalog=page.getByRole('region',{name:'全部候選結果',exact:true});
 await catalog.getByLabel('比較角色').selectOption('unselected');
 const response=await page.request.get(`${base}/api/runs/${run}/reports/1/candidates?role=unselected`);
 const listing=await response.json();
 const similar=listing.items.find(e=>e.summary?.selection?.similar_priority_id);
 assert(similar,'Require a real similar alternative, not a vacuous click test');
 const alternate=catalog.locator(`[data-candidate-id="${similar.candidate_id}"]`);
 await alternate.getByRole('button').click();
 await page.locator(`[data-selected-candidate="${similar.candidate_id}"]`).waitFor();
 await page.getByRole('button',{name:'查看這個相似候選的完整證據',exact:true}).click();
 await page.waitForFunction(id=>document.activeElement?.getAttribute('data-selected-candidate')===id,similar.summary.selection.similar_priority_id);
 assert.deepEqual(errors,[]);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 console.log(JSON.stringify({width,priorities:report.candidates.length,errors}));await page.close();
}}finally{await browser.close();}

import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const [htmlPath,jsonPath]=process.argv.slice(2),expected=JSON.parse(await readFile(jsonPath,'utf8'));
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const context=await browser.newContext({offline:true,viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));await page.goto(pathToFileURL(htmlPath).href);
 const data=JSON.parse(await page.locator('#evidence').textContent()),seen=new Set();
 for(let i=0;i<data.income_groups.length;i++){
  const group=data.income_groups[i];await page.locator('#income-group').selectOption(String(i));
  for(const point of group.points){
   const entry=expected.entries.find(e=>e.candidate_id===point.candidate_id);assert(entry);seen.add(point.candidate_id);
   assert.equal(group.window_hours,entry.window_hours);assert.equal(group.ad_format,entry.summary.event_spec.predicate.ad_format??'all');
   assert.equal(point.threshold_usd,entry.summary.event_spec.predicate.threshold);
   assert.equal(point.coverage,entry.summary.coverage);assert.equal(point.difference_usd,entry.summary.difference_usd);
  }
  const xmin=Math.min(...group.points.map(p=>p.threshold_usd)),xmax=Math.max(...group.points.map(p=>p.threshold_usd));
  for(const metric of ['coverage','difference_usd']){
   const known=group.points.filter(p=>p[metric]!==null),svg=page.locator(`#income-plots svg[data-metric="${metric}"]`);
   assert.equal(await svg.count(),known.length?1:0);if(!known.length)continue;
   assert.equal(Number(await svg.getAttribute('data-x-min')),xmin);assert.equal(Number(await svg.getAttribute('data-x-max')),xmax);
   assert.deepEqual(await svg.locator('circle').evaluateAll(nodes=>nodes.map(n=>n.dataset.candidateId)),known.map(p=>p.candidate_id));
   await svg.locator('circle').first().click();
   const raw=await page.locator('#card details').last().locator('pre').textContent();
   assert.equal(JSON.parse(raw).candidate_id,known[0].candidate_id);
  }
 }
 assert.deepEqual([...seen].sort(),expected.entries.filter(e=>e.summary?.event_spec.predicate.op==='revenue_sum').map(e=>e.candidate_id).sort());
 const summary=await page.locator('#search-summary td').allTextContents();
 assert.deepEqual(summary,[expected.search.enumerated,expected.search.unique_before_cap,expected.search.selected_count,expected.search.pruning.length].map(String));
 assert.equal(await page.locator('#pruning-table details').count(),Math.min(50,expected.search.pruning.length));
 await page.locator('#income-group').selectOption(String(data.income_groups.findIndex(g=>g.points.some(p=>p.difference_usd<0))));
 await page.locator('#income').scrollIntoViewIfNeeded();await page.screenshot({path:htmlPath+'.income-desktop.png'});
 await page.setViewportSize({width:390,height:900});await page.locator('#income').scrollIntoViewIfNeeded();await page.screenshot({path:htmlPath+'.income-mobile.png'});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({groups:data.income_groups.length,points:seen.size,errors}));
}finally{await browser.close();}

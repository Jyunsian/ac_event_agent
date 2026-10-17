import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';

const [htmlPath,jsonPath]=process.argv.slice(2);
const expected=JSON.parse(await readFile(jsonPath,'utf8'));
const browser=await chromium.launch({channel:'chrome',headless:true});
try {
  const context=await browser.newContext({offline:true,viewport:{width:1440,height:1000}});
  const page=await context.newPage(),errors=[],network=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
  await page.goto(pathToFileURL(htmlPath).href);
  const embedded=await page.locator('#evidence').textContent();
  for(const key of Object.keys(expected))assert.deepEqual(JSON.parse(embedded)[key],expected[key]);
  const fmt=v=>v==null?'未知／此版本未計算':String(v);
  let checked=0;
  for(const entry of [...expected.entries].sort((a,b)=>a.candidate_id.localeCompare(b.candidate_id))){
    // ID search also confirms every non-priority candidate remains reachable offline.
    await page.locator('#search').fill(entry.candidate_id);
    assert.equal(await page.locator('#rows tr').count(),1);
    const cells=await page.locator('#rows tr td').allTextContents(),s=entry.summary||{};
    assert.equal(cells[1],fmt(s.triggered_users)+' / '+fmt(s.untriggered_users));
    assert.equal(cells[2],fmt(s.coverage));
    assert.equal(cells[3],fmt(s.triggered_arpu_usd)+' / '+fmt(s.untriggered_arpu_usd));
    assert.equal(cells[4],fmt(s.difference_usd));
    assert.equal(cells[5],fmt(s.median_seconds)+' / '+fmt(s.p90_seconds));
    await page.locator('#rows button').click();
    const detail=expected.details.find(d=>d.candidate_id===entry.candidate_id);
    const raw=await page.locator('#card details').last().locator('pre').textContent();
    assert.deepEqual(JSON.parse(raw),detail);
    assert.equal(await page.locator('#card').isVisible(),true);checked++;
  }
  await page.locator('#search').fill('');
  assert.equal(await page.locator('#rows tr').count(),Math.min(50,expected.entries.length));
  for(const [control,values,predicate] of [
    ['window',[...new Set(expected.entries.map(e=>String(e.window_hours)))],(e,v)=>String(e.window_hours)===v],
    ['family',['atom','compound','sequence'],(e,v)=>e.summary?.family===v],
    ['format',[...new Set(expected.entries.flatMap(e=>e.summary?.ad_formats||[]))],(e,v)=>(e.summary?.ad_formats||[]).includes(v)],
    ['role',['unselected','價值差較大','覆蓋較廣','達標較快'],(e,v)=>v==='unselected'?!(expected.report.catalog.priority_ids||[]).includes(e.candidate_id):e.summary?.role===v],
  ]) {
    for(const value of values){
      await page.locator('#'+control).selectOption(value);
      const count=expected.entries.filter(e=>predicate(e,value)).length;
      assert.match(await page.locator('#count').innerText(),new RegExp('符合 '+count+' /'));
      assert.equal(await page.locator('#rows tr').count(),Math.min(50,count));
    }
    await page.locator('#'+control).selectOption('');
  }
  await page.screenshot({path:htmlPath+'.desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:htmlPath+'.mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
  console.log(JSON.stringify({checked,offline:true,pageErrors:errors,networkRequests:network}));
} finally {await browser.close();}

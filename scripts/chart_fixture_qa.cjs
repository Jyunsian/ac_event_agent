const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
module.exports=async function chartFixtureQA(url,output){
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(`${url}/test/chart-fixture.html`);
  await page.getByRole('heading',{name:'合成圖表邊界測試 · 非客戶資料'}).waitFor();
  await page.locator('[data-chart-type="heatmap"] svg').waitFor();
  assert.equal(await page.getByRole('alert').count(),1);
  assert.match(await page.getByRole('alert').textContent(),/CHART_SCHEMA_INVALID/);
  const scatter=page.locator('[data-chart-type="scatter"]');
  assert.match(await scatter.textContent(),/可顯示 3 \/ 4/);
  assert.equal(await scatter.locator('tbody tr').count(),4);
  assert.equal(await scatter.locator('tbody tr').nth(2).locator('td').last().getAttribute('data-value'),'1000000000000');
  assert.equal(await scatter.locator('tbody tr').nth(2).locator('td').last().textContent(),'1,000,000,000,000 美元');
  assert.match(await page.locator('[data-chart-type="heatmap"]').textContent(),/可顯示 3 \/ 4/);
  const heat=page.locator('[data-chart-type="heatmap"]');
  await heat.scrollIntoViewIfNeeded();
  // Move onto the center of the lower-left heat cell in the rendered SVG.
  const plot=heat.locator('div[role="img"]');const box=await plot.boundingBox();
  await page.mouse.move(box.x+70+(box.width-100)/4,box.y+45+(340-125)*3/4);
  await page.waitForFunction(()=>document.querySelector('[data-chart-type="heatmap"] svg')?.textContent.includes('分母：至少符合其中一個條件的人數'));
  assert.match(await heat.locator('svg').textContent(),/分析人群：100 位用戶/);
  await heat.screenshot({path:path.join(output,'heatmap-tooltip.png')});
  for(const width of [1280,390]){
   await page.setViewportSize({width,height:900});
   // ResizeObserver updates the SVG after the viewport event, not synchronously.
   await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   for(const type of ['scatter','line','heatmap']){
    const section=page.locator(`[data-chart-type="${type}"]`);await section.scrollIntoViewIfNeeded();
    const invalid=await section.locator('svg').evaluate(svg=>/NaN|Infinity/.test(svg.outerHTML));assert.equal(invalid,false);
    await section.screenshot({path:path.join(output,`synthetic-${type}-${width}.png`)});
   }
  }
  assert.deepEqual(errors,[]);
  await scatter.getByText('查看圖表數據表',{exact:true}).focus();await page.keyboard.press('Enter');
  assert.equal(await scatter.locator('tbody tr').first().locator('td').first().textContent().then(s=>s.includes('極長中文廣告事件名稱_'.repeat(12))),true);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  const table=scatter.getByRole('region');await table.focus();await page.keyboard.press('ArrowRight');
  await page.waitForFunction(()=>document.querySelector('[data-chart-type="scatter"] .data-table').scrollLeft>0);
  await scatter.screenshot({path:path.join(output,'a11y-long-event-390.png')});
  fs.writeFileSync(path.join(output,'synthetic-chart-checks.json'),JSON.stringify({synthetic:true,errors,checks:['three finite scatter points','1e12 table retained','unknown heat cell not zero','invalid type rejected','SVG finite','1280 and 390 no overflow']},null,2),{flag:'wx'});
 }finally{await browser.close();}
};

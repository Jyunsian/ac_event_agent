const assert=require('node:assert/strict');
const path=require('node:path');
module.exports=async function messageFixtureQA(browser,base,directory){
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 try{
  await page.goto(`${base}/test/message-fixture.html`);
  const content=page.locator('.assistant-content');await content.waitFor();
  assert.equal(await content.locator('h4').innerText(),'先看結論');
  assert.equal(await content.locator('strong').first().innerText(),'不能判定投放會提升');
  assert.equal(await content.locator('li').count(),2);
  assert.equal(await content.locator('table tbody tr').count(),2);
  assert.match(await content.locator('table').innerText(),/0\.00000001 美元/);
  assert.equal(await content.locator('script,img,iframe,a').count(),0);
  const codeDetails=content.locator('details').filter({hasText:'查看補充設定或程式內容'});
  assert.equal(await codeDetails.getAttribute('open'),null);
  await codeDetails.locator('summary').click();
  assert.match(await codeDetails.locator('pre').innerText(),/<script>window.__injected=1<\/script>/);
  await codeDetails.locator('summary').click();
  assert.equal(await page.evaluate(()=>window.__injected),undefined);
  assert.equal(await content.locator('.reference-button').count(),3);
  assert.equal(await content.locator('.reference-unavailable').count(),1);
  assert(!((await content.innerText()).includes('report:')));
  await content.getByRole('button',{name:'查看證據 1',exact:true}).last().click();
  assert.equal(await page.getByLabel('已選證據').textContent(),'report:00000000-0000-0000-0000-000000000001#/summary');
  await page.locator('.message-original summary').click();
  assert.match(await page.locator('.message-original pre').innerText(),/report:00000000-0000-0000-0000-000000000002/);
  await page.locator('.message-original summary').click();
  for(const width of [1280,390]){await page.setViewportSize({width,height:900});assert((await page.evaluate(()=>document.documentElement.scrollWidth))<=width);await page.screenshot({path:path.join(directory,`message-safe-${width}.png`)});}
 }finally{await page.close();}
};

const {chromium}=require('playwright');
const path=require('path');
(async()=>{
  const source=process.argv[2],out=process.argv[3];if(!source||!out)throw new Error('usage: html screenshot-dir');
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844]]){
    const page=await browser.newPage({viewport:{width,height}});const errors=[];page.on('pageerror',error=>errors.push(String(error)));
    await page.goto('file://'+path.resolve(source));await page.waitForLoadState('load');
    const count=await page.locator('#count').textContent();if(!/可繪製 \d+ \/ 全部 \d+/.test(count||''))throw new Error('COUNT_MISSING');
    if(await page.locator('#category option').count()>1){await page.locator('#category').selectOption({index:1});await page.locator('#category').selectOption('all');}
    if(await page.locator('svg circle').count()){const point=page.locator('svg circle').first();await point.hover();if(!await point.locator('title').textContent())throw new Error('HOVER_DETAIL_MISSING');await point.focus();await page.keyboard.press('Enter');if(!await page.locator('#detail pre').count())throw new Error('DETAIL_NOT_OPENED');}
    if(!await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))throw new Error('HORIZONTAL_OVERFLOW');
    await page.screenshot({path:path.join(out,`${name}.png`),fullPage:true});
    if(errors.length)throw new Error(errors.join('\n'));await page.close();
  }
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});

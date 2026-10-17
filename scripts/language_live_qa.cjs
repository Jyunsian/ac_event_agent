// Read-only smoke check against the local, persistent synthetic workspace.
const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const [url, output] = process.argv.slice(2);
  assert(url && output, 'Provide report URL and new evidence directory');
  fs.mkdirSync(output);
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  const checks = [];
  try {
    for (const width of [1440,390]) {
      const page = await browser.newPage({viewport:{width,height:900}});
      const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
      await page.goto(url);
      await page.getByRole('tab',{name:'概覽',exact:true}).waitFor();
      await page.getByRole('heading',{name:'目前還不能選出值得優先測試的事件',exact:true}).waitFor();
      for (const tab of ['概覽','候選事件','圖表','資料品質']) {
        await page.getByRole('tab',{name:tab,exact:true}).click();
        await page.screenshot({path:`${output}/report-${tab}-${width}.png`});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      }
      if(width<1024)await page.getByRole('button',{name:'對話',exact:true}).click();
      const provider=await (await page.request.get(new URL('/api/agent/status',url).href)).json();
      await page.getByText(provider.available?'可提問':'暫時無法提問',{exact:true}).waitFor();
      await page.screenshot({path:`${output}/agent-status-${width}.png`});
      for(const route of ['/','/upload','/history']) {
        await page.goto(new URL(route,url).href);
        await page.locator('h1:visible,h2:visible,h3:visible').first().waitFor();
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
        await page.screenshot({path:`${output}/${route.slice(1)||'empty'}-${width}.png`});
      }
      assert.deepEqual(errors,[]);
      checks.push({width,pages:['report four tabs','agent status','empty','upload','history'],agentAvailable:provider.available,pageErrors:errors,overflow:false});
      await page.close();
    }
    fs.writeFileSync(`${output}/checks.json`,JSON.stringify(checks,null,2),{flag:'wx'});
    console.log(JSON.stringify(checks));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

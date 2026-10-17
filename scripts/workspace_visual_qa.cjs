const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const [url, output] = process.argv.slice(2);
  assert(url && output, 'Usage: workspace_visual_qa.cjs URL NEW_OUTPUT_DIRECTORY');
  fs.mkdirSync(output);
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  const evidence = [];
  try {
    for (const [width,height] of [[1440,900],[1280,800],[768,900],[390,844]]) {
      const page = await browser.newPage({viewport:{width,height}});
      const errors = []; page.on('pageerror', error => errors.push(String(error)));
      await page.goto(url);
      await page.getByText('這份樣本適合核對計算，不適合做投放決策。').waitFor();
      const state = await page.evaluate(() => ({
        bodyX:document.documentElement.scrollWidth > innerWidth,
        bodyY:document.documentElement.scrollHeight > innerHeight,
        chatWidth:document.querySelector('.chat-panel').getBoundingClientRect().width,
        resultsWidth:document.querySelector('.results-panel').getBoundingClientRect().width,
        synthetic:document.querySelector('.fixture-notice').textContent,
      }));
      assert.equal(state.bodyX, false); assert.equal(state.bodyY, false);
      assert.match(state.synthetic, /示範資料/);
      await page.screenshot({path:path.join(output,`workspace-${width}.png`)});
      if (width >= 1024) {
        assert.equal(state.chatWidth, 360);
        const splitter = page.getByRole('separator');
        const before = {composer:await page.locator('.composer').boundingBox(), tabs:await page.getByRole('tablist').boundingBox()};
        await page.locator('.chat-scroll').evaluate(el => { el.scrollTop = 250; });
        const leftScroll = await page.locator('.chat-scroll').evaluate(el => el.scrollTop);
        const chatOverflows=await page.locator('.chat-scroll').evaluate(el=>el.scrollHeight>el.clientHeight);
        assert(!chatOverflows || leftScroll>0,'Overflowing chat must scroll independently');
        assert.equal(await page.locator('.result-scroll').evaluate(el => el.scrollTop), 0);
        await page.locator('.result-scroll').evaluate(el => { el.scrollTop = 300; });
        assert.equal(await page.locator('.chat-scroll').evaluate(el => el.scrollTop), leftScroll);
        assert(await page.locator('.result-scroll').evaluate(el => el.scrollTop) > 0, 'Results must scroll independently');
        assert.deepEqual(await page.locator('.composer').boundingBox(), before.composer);
        assert.deepEqual(await page.getByRole('tablist').boundingBox(), before.tabs);
        await splitter.focus(); await page.keyboard.press('End');
        assert.equal(await splitter.getAttribute('aria-valuenow'), '480');
        await page.keyboard.press('ArrowRight'); assert.equal(await splitter.getAttribute('aria-valuenow'), '480');
        await page.keyboard.press('Home'); assert.equal(await splitter.getAttribute('aria-valuenow'), '320');
        await page.keyboard.press('ArrowLeft'); assert.equal(await splitter.getAttribute('aria-valuenow'), '320');
        const box = await splitter.boundingBox();
        await page.mouse.move(box.x+2,box.y+100); await page.mouse.down();
        await page.mouse.move(box.x+102,box.y+100,{steps:5}); await page.mouse.up();
        assert.equal(await splitter.getAttribute('aria-valuenow'), '420');
        await page.reload(); await page.getByRole('separator').waitFor();
        assert.equal(await page.getByRole('separator').getAttribute('aria-valuenow'), '420');
      } else {
        assert.equal(state.chatWidth, 0);
        await page.getByRole('button',{name:'對話',exact:true}).click();
        await page.getByLabel('想問什麼？').fill('長中文草稿：'+ '保留同一份資料。'.repeat(20));
        await page.getByRole('button',{name:'結果',exact:true}).click();
        await page.getByRole('button',{name:'對話',exact:true}).click();
        assert.match(await page.getByLabel('想問什麼？').inputValue(), /長中文草稿/);
        await page.screenshot({path:path.join(output,`chat-${width}.png`)});
        await page.getByRole('button',{name:'結果',exact:true}).click();
      }
      await page.getByRole('tab',{name:'概覽',exact:true}).focus();
      await page.keyboard.press('ArrowRight');
      assert.equal(await page.getByRole('tab',{name:'候選事件',exact:true}).getAttribute('aria-selected'),'true');
      await page.getByRole('button',{name:'6 小時內累積 5 次激勵廣告',exact:true}).click();
      await page.getByRole('heading',{name:'用戶何時首次符合條件？'}).waitFor();
      assert.equal(await page.locator('.selected-detail pre').isVisible(),false);
      await page.getByText('查看範例用戶與精確時間',{exact:true}).click();
      assert.equal(await page.locator('.selected-detail pre').isVisible(),true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),false);
      assert.equal(errors.length,0,errors.join('\n'));
      evidence.push({width,height,...state,checks:'splitter bounds/drag/reload or mobile draft; independent scroll; fixed chrome; tabs/detail',errors});
      await page.close();
    }
    const empty = await browser.newPage();
    await empty.goto(new URL('/',url).href);
    await empty.getByRole('heading',{name:'從一份用戶資料開始'}).waitFor();
    assert.equal(await empty.locator('.fixture-notice').count(),0);
    assert.equal(await empty.getByRole('button',{name:'送出',exact:true}).isDisabled(),true);
    await empty.close();
    fs.writeFileSync(path.join(output,'checks.json'), JSON.stringify({evidence,emptyState:true},null,2),{flag:'wx'});
    console.log(JSON.stringify({evidence,emptyState:true}));
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});

const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const [base,parent,child,conversation,directory,mode='success']=process.argv.slice(2);
const toolLabel=mode==='segment'?'安排指定人群的分析 · 已完成':'安排另一組條件的分析 · 已完成';
(async()=>{
 fs.mkdirSync(directory,{recursive:true});
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`${base}/workspace?run=${parent}&conversation=${conversation}`);
  await page.getByRole('heading',{name:/目前還不能選出值得優先測試的事件|找到有歷史資料支持的事件條件/}).waitFor();
  await page.getByText(toolLabel,{exact:true}).waitFor();
  await page.getByText('查看分析進度與結果 · 已完成',{exact:true}).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('run'),parent);
  await page.screenshot({path:`${directory}/parent-and-completed-tools.png`});
  await page.getByRole('button',{name:'查看結果',exact:true}).last().click();
  await page.waitForURL(url=>url.searchParams.get('run')===child&&url.searchParams.has('artifact'));
  await page.getByText('查看分析進度與結果 · 已完成',{exact:true}).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('conversation'),conversation);
  assert.equal(await page.getByRole('alert').count(),0);
  await page.getByRole('tab',{name:'候選事件',exact:true}).click();
  if(mode==='segment')await page.getByRole('region',{name:'分群分母與收益',exact:true}).waitFor();
  else await page.getByRole('button',{name:/^優先比較（/}).waitFor();
  if(mode==='segment'){
    const region=page.getByRole('region',{name:'分群分母與收益',exact:true});
    assert.equal(await region.locator('[data-value="0.1"]').count()>0,true);
    assert((await region.textContent()).includes('0.1 美元'));
    assert((await region.textContent()).includes('這個人群的人數太少'));
    await page.getByRole('heading',{name:'國家：US 的用戶分析'}).waitFor();
  }
  await page.screenshot({path:`${directory}/child-3h-report.png`});
  await page.reload();await page.getByText(toolLabel,{exact:true}).waitFor();
  assert.equal(await page.getByRole('alert').count(),0);
  const writes=[];
  page.on('request',request=>{if(['POST','PUT','DELETE','PATCH'].includes(request.method()))writes.push(request.url());});
  assert.equal(new URL(page.url()).searchParams.get('version'),'1');
  for(const selected of [parent,child]){
    await page.getByLabel('檢視報告版本 v1',{exact:true}).click();
    const link=page.locator(`.branch-list a[href*="run=${selected}"]`);
    await link.waitFor();await link.click();
    await page.waitForURL(url=>url.searchParams.get('run')===selected&&url.searchParams.get('version')==='1');
    await page.locator(`.report-panel[data-run-id="${selected}"]`).waitFor();
    await page.getByRole('tab',{name:'圖表',exact:true}).click();
    assert.equal(await page.getByRole('link',{name:'匯出',exact:true}).getAttribute('href'),`/api/runs/${selected}/reports/1/html`);
    await page.getByLabel('更多匯出格式',{exact:true}).click();
    for(const format of ['html','csv','json']){
      const href=await page.getByRole('link',{name:`下載 ${format.toUpperCase()}`,exact:true}).getAttribute('href');
      assert.equal(href,`/api/runs/${selected}/reports/1/${format}`);
      const download=await page.request.get(base+href);assert.equal(download.status(),200);
      assert(download.headers()['content-disposition'].includes(`report-${selected}-v1.${format}`));
      if(format==='json')assert.equal((await download.json()).run_id,selected);
    }
    await page.getByLabel('更多匯出格式',{exact:true}).click();
    await page.getByRole('tab',{name:'候選事件',exact:true}).click();
    if(selected===child&&mode==='segment')await page.getByRole('region',{name:'分群分母與收益',exact:true}).waitFor();
    else await page.getByRole('button',{name:/^優先比較（/}).waitFor();
    await page.reload();await page.getByText(toolLabel,{exact:true}).waitFor();
    assert.equal(new URL(page.url()).searchParams.get('run'),selected);
    assert.equal(await page.getByRole('alert').count(),0);
  }
  assert.deepEqual(writes,[],'Selecting published results must not submit analysis or chat');
  await page.screenshot({path:`${directory}/branch-selection.png`});
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'對話',exact:true}).click();
  assert((await page.evaluate(()=>document.documentElement.scrollWidth))<=390);
  await page.screenshot({path:`${directory}/child-chat-mobile.png`});
  const response=await page.request.get(`${base}/api/runs/${parent}/view`);
  assert.equal((await response.json()).ready,true);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({synthetic:true,persistentCards:true,childReference:true,conversationPreserved:true,
    refresh:true,branchPicker:true,readOnlySelection:true,exportContext:true,parentReadable:true,mobileOverflow:false,pageErrors:errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

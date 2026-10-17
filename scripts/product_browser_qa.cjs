const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const [base,manifest,directory]=process.argv.slice(2);
(async()=>{
 fs.mkdirSync(directory,{recursive:true});
 const files=JSON.parse(fs.readFileSync(manifest));
 const browser=await chromium.launch({channel:'chrome',headless:true,
  args:process.env.AC_TEST_DOCKER_HOST==='1'?['--host-resolver-rules=MAP host.docker.internal 127.0.0.1','--no-proxy-server']:[]});
 let page;
 try{
  page=await browser.newPage({viewport:{width:1440,height:900},acceptDownloads:true});
  page.setDefaultTimeout(60000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/history');
  assert.equal(await page.locator('a[href^="/runs/"]').count(),0);
  await page.goto(base+'/upload');
  await page.getByLabel('App ID',{exact:true}).fill('synthetic');
  await page.getByLabel('分析名稱',{exact:true}).fill('完整流程合成驗收');
  await page.getByRole('button',{name:'繼續上傳資料',exact:true}).click();
  await page.getByLabel('用戶表',{exact:true}).setInputFiles(files.users);
  await page.getByText('檔案已完整上傳，內容檢查通過。接著請確認欄位與時間說明。',{exact:true}).waitFor();
  await page.getByLabel('事件檔（可多選）',{exact:true}).setInputFiles(files.events);
  await page.getByText('檔案已完整上傳，內容檢查通過。接著請確認欄位與時間說明。',{exact:true}).waitFor();
  for(const [role,fields] of Object.entries(files.mapping))for(const field of Object.keys(fields)){
   await page.locator(`[data-field="${role}.${field}"]`).fill(field);
  }
  assert.equal(await page.getByRole('button',{name:'填入範例資料的時間與說明'}).count(),0);
  const metadata=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../tests/fixtures/hand/export.json')));
  const utcInput=value=>value.replace(/:00Z$/,''); // Canonical minute precision of this fixture.
  await page.getByLabel('資料完整截止時間（UTC）').fill(utcInput(metadata.complete_through));
  await page.getByLabel('檔案匯出時間（UTC）').fill(utcInput(metadata.exported_at));
  await page.getByLabel(/^時間起點/).selectOption(metadata.origin);
  await page.getByLabel('如何識別同一位用戶？').fill(metadata.id_policy);
  await page.getByLabel(/^收益何時可取得/).selectOption(metadata.revenue_timing);
  await page.getByLabel('這是合成測試資料',{exact:true}).check();
  await page.getByRole('button',{name:'開始分析',exact:true}).click();
  await page.getByRole('link',{name:/查看分析進度/}).click();
  const parent=new URL(page.url()).pathname.split('/').at(-1);
  await page.getByRole('link',{name:/開啟.*報告|開啟.*工作區/}).click();
  await page.getByRole('heading',{name:'目前還不能選出值得優先測試的事件'}).waitFor();
  assert.equal(await page.locator('.panels > aside').count(),1);
  assert.equal(await page.locator('.panels > main').count(),1);
  assert.equal(await page.locator('input[type="password"]').count(),0);
  const original=await (await page.request.get(`${base}/api/runs/${parent}/reports/1/json`)).body();
  const questions=['改看前 3 小時','只看美國用戶','這三個候選的人群重疊嗎','覆蓋率高一點'];
  const results=[];
  for(const question of questions){
   await page.getByLabel('分析草稿').fill(question);
   await page.getByRole('button',{name:'送出',exact:true}).click();
   await page.locator('.chat-message').filter({has:page.getByText(question,{exact:true})}).getByText('已完成',{exact:true}).waitFor();
   assert.equal(await page.getByText(/回覆失敗/).count(),0);
   const conversation=new URL(page.url()).searchParams.get('conversation');assert(conversation);
   const response=await page.request.get(`${base}/api/conversations/${conversation}/events`);
   results.push({question,events:(await response.json()).events});
   await page.reload();await page.getByLabel('分析草稿').waitFor();
   await page.getByRole('heading',{name:'目前還不能選出值得優先測試的事件'}).waitFor();
   assert.equal(new URL(page.url()).searchParams.get('run'),parent);
  }
  await page.screenshot({path:path.join(directory,'product-desktop.png')});
  await page.getByRole('button',{name:'查看結果',exact:true}).last().click();
  await page.waitForURL(url=>url.searchParams.get('run')!==parent);
  const child=new URL(page.url()).searchParams.get('run');
  await page.getByLabel('更多匯出格式').click();
  for(const format of ['html','json','csv']){
   const link=page.getByRole('link',{name:`下載 ${format.toUpperCase()}`,exact:true});
   assert.equal(await link.getAttribute('href'),`/api/runs/${child}/reports/1/${format}`);
   const waiting=page.waitForEvent('download');await link.click();
   const download=await waiting;assert.equal(await download.failure(),null);
   await download.saveAs(path.join(directory,`report.${format}`));
  }
  assert.equal(JSON.parse(fs.readFileSync(path.join(directory,'report.json'))).run_id,child);
  assert.deepEqual(await (await page.request.get(`${base}/api/runs/${parent}/reports/1/json`)).body(),original);
  await page.getByLabel('更多匯出格式').click();
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'對話',exact:true}).click();
  assert((await page.evaluate(()=>document.documentElement.scrollWidth))<=390);
  await page.screenshot({path:path.join(directory,'product-mobile.png')});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(directory,'checks.json'),JSON.stringify({synthetic:true,parent,child,results,errors},null,2),{flag:'wx'});
  console.log(JSON.stringify({synthetic:true,parent,child,questions:questions.length}));
 }catch(error){
  if(page){await page.screenshot({path:path.join(directory,'failure.png')});fs.writeFileSync(path.join(directory,'failure.txt'),`${page.url()}\n${await page.locator('body').innerText()}`);}
  throw error;
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

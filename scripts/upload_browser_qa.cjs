const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async()=>{
  const [url, filesPath, output] = process.argv.slice(2);
  const files = JSON.parse(fs.readFileSync(filesPath)); fs.mkdirSync(output);
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[], storageResponses=[];
    page.on('pageerror',e=>errors.push(String(e)));
    page.on('response',r=>{if(r.request().method()==='PUT' && new URL(r.url()).origin!==new URL(url).origin)storageResponses.push(r.status());});
    await page.goto(url+'/upload');
    assert.equal(await page.getByRole('button',{name:'填入範例資料的時間與說明'}).count(),0);
    await page.goto(url+'/upload?demo=hand');
    await page.getByLabel('App ID',{exact:true}).fill('synthetic');
    await page.getByLabel('分析名稱',{exact:true}).fill('真瀏覽器上傳 Synthetic');
    await page.getByRole('button',{name:'繼續上傳資料',exact:true}).click();
    await page.getByText('1. 上傳與續傳',{exact:true}).waitFor();
    await page.getByLabel('用戶表',{exact:true}).setInputFiles({name:'unsupported.txt',mimeType:'text/plain',buffer:Buffer.from('synthetic')});
    await page.getByRole('alert').filter({hasText:'請選擇 CSV 或 Parquet'}).waitFor();
    await page.getByLabel('用戶表',{exact:true}).setInputFiles(files.users);
    await page.getByText('檔案已完整上傳，內容檢查通過。接著請確認欄位與時間說明。',{exact:true}).waitFor();
    // Fault injection only: stop the second signing request after first part truly reached S3.
    let interrupted=false;
    await page.route('**/api/uploads/*/parts',async route=>{
      if(!interrupted && route.request().postDataJSON().part_number===2){interrupted=true;await route.abort();}
      else await route.continue();
    });
    await page.getByLabel('事件檔（可多選）',{exact:true}).setInputFiles(files.events[0]);
    await page.getByRole('alert').filter({hasText:'目前無法連線'}).waitFor();
    assert(interrupted && storageResponses.length>=2);
    await page.unroute('**/api/uploads/*/parts');
    await page.reload();
    const resumeLabel='重新選取 '+path.basename(files.events[0]);
    await page.getByRole('button',{name:'檢查完成狀態：'+path.basename(files.events[0]),exact:true}).click();
    await page.getByRole('alert').filter({hasText:'檔案還沒有全部上傳'}).waitFor();
    const original=fs.readFileSync(files.events[0]);
    await page.getByLabel(resumeLabel,{exact:true}).setInputFiles({name:path.basename(files.events[0]),mimeType:'text/csv',buffer:Buffer.alloc(original.length,120)});
    await page.getByRole('alert').filter({hasText:'這份檔案的內容與原本不同'}).waitFor();
    await page.getByLabel(resumeLabel,{exact:true}).setInputFiles(files.events[0]);
    await page.getByText('檔案已完整上傳，內容檢查通過。接著請確認欄位與時間說明。',{exact:true}).waitFor();
    await page.getByLabel('事件檔（可多選）',{exact:true}).setInputFiles(files.events[1]);
    await page.getByText('檔案已完整上傳，內容檢查通過。接著請確認欄位與時間說明。',{exact:true}).waitFor();
    await page.getByRole('button',{name:'填入範例資料的時間與說明'}).click();
    await page.getByLabel('行為紀錄：單次廣告收益（美元）',{exact:true}).fill('revenue_usd');
    await page.getByLabel('行為紀錄：資料可取得時間',{exact:true}).fill('available_at');
    await page.getByLabel('資料完整截止時間（UTC）').fill('');
    await page.getByRole('button',{name:'儲存欄位與資料說明',exact:true}).click();
    assert.equal(await page.locator('input[type="datetime-local"]').first().evaluate(el=>el.validity.valueMissing),true);
    await page.getByLabel('資料完整截止時間（UTC）').fill('2026-01-14T00:00');
    await page.getByLabel('檔案匯出時間（UTC）').fill('2026-01-13T00:00');
    await page.getByRole('button',{name:'儲存欄位與資料說明',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'請檢查資料截止時間'}).waitFor();
    await page.getByRole('button',{name:'填入範例資料的時間與說明'}).click();
    const save=async()=>{await page.getByRole('button',{name:'儲存欄位與資料說明',exact:true}).click();await page.getByText('欄位與資料說明已儲存，重新開啟頁面仍會保留。',{exact:true}).waitFor();};
    await save();
    await page.getByLabel('行為紀錄：單次廣告收益（美元）',{exact:true}).fill('different_column');await save();
    await page.getByLabel('行為紀錄：單次廣告收益（美元）',{exact:true}).fill('revenue_usd');await save();
    await page.reload();
    await page.getByLabel('行為紀錄：單次廣告收益（美元）',{exact:true}).waitFor();
    await page.waitForFunction(()=>document.querySelector('input[value="revenue_usd"]'));
    assert.equal(await page.getByLabel('行為紀錄：單次廣告收益（美元）',{exact:true}).inputValue(),'revenue_usd');
    assert.equal(await page.getByLabel('這是合成測試資料',{exact:true}).isChecked(),true);
    await page.getByLabel('用戶名冊：App 識別碼',{exact:true}).fill('');
    await page.getByRole('button',{name:'開始分析',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'請填寫標示「必填」'}).waitFor();
    await page.getByLabel('用戶名冊：App 識別碼',{exact:true}).fill('app_id');
    await page.screenshot({path:path.join(output,'upload-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    await page.evaluate(()=>scrollTo(0,0));
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(output,'upload-mobile.png')});
    await page.getByRole('button',{name:'開始分析',exact:true}).click();
    await page.getByText('分析已排入等待，關閉頁面不會取消。你可以查看進度，完成後再開啟報告。',{exact:true}).waitFor();
    const datasetId=new URL(page.url()).searchParams.get('dataset');
    const records=await (await page.request.get(url+`/api/datasets/${datasetId}/uploads`)).json();
    assert.equal(records.uploads.length,3); assert(records.uploads.every(u=>u.status==='completed'));
    assert(records.uploads.every(u=>!('multipart_id' in u) && !('object_key' in u)));
    assert.equal(errors.length,0,errors.join('\n'));assert(storageResponses.every(s=>s===200));
    fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify({datasetId,uploads:records.uploads,storageResponses,errors,
      checks:['real multipart PUT','interruption and resume','missing parts visible','unsupported format','same-size wrong file rejection','invalid metadata','required mapping','A-B-A persistence','queued baseline','mobile no overflow']},null,2),{flag:'wx'});
    console.log(JSON.stringify({datasetId,uploads:records.uploads.length,realStoragePuts:storageResponses.length,errors}));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

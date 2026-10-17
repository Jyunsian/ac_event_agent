const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const [base,current,source,cid,dir]=process.argv.slice(2);
(async()=>{
 fs.mkdirSync(dir,{recursive:true});
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method()))writes.push(r.url());});
  await page.goto(`${base}/workspace?run=${current}&conversation=${cid}`);
  const reference=page.locator('.chat-message').filter({hasText:'合成歷史觀察引用'}).getByRole('button',{name:'查看證據 1'});
  await reference.waitFor();assert.equal(new URL(page.url()).searchParams.get('run'),current);
  await reference.click();await page.waitForURL(url=>url.searchParams.get('run')===source);
  await page.getByRole('region',{name:'完整候選證據',exact:true}).waitFor();
  await page.waitForFunction(id=>new URL(location.href).searchParams.get('conversation')!==id,cid);
  assert.equal(await page.getByRole('alert').count(),0);
  assert.equal(new URL(page.url()).searchParams.get('version'),'1');
  await page.reload();await page.getByRole('region',{name:'完整候選證據',exact:true}).waitFor();
  assert.equal(await page.getByRole('alert').count(),0);
  await page.screenshot({path:`${dir}/historical-finding.png`});
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  console.log(JSON.stringify({synthetic:true,crossBatchReference:true,conversationRebound:true,refresh:true,readOnly:true}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

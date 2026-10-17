const {chromium}=require('playwright');
const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
 const [url,output,countArg]=process.argv.slice(2);assert(url&&output);
 const count=Number(countArg||5);assert(Number.isInteger(count)&&count>0&&count<=5);
 fs.mkdirSync(output);
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const checks=[];
 try{
  for(const width of [1440,390]){
   const page=await browser.newPage({viewport:{width,height:900}});
   const errors=[];page.on('pageerror',e=>errors.push(String(e)));
   await page.goto(url);
   if(width<1024)await page.getByRole('button',{name:'對話',exact:true}).click();
   await page.locator('.assistant-content').nth(count-1).waitFor();
   assert.equal(await page.locator('.assistant-content').count(),count);
   assert.equal(await page.locator('.reference-unavailable').count(),0);
   for(let i=0;i<count;i++){
    const answer=page.locator('.assistant-content').nth(i);
    assert((await answer.locator('.reference-button').count())>0);
    assert(!/report:[a-f0-9-]+#/.test(await answer.innerText()));
    await answer.scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:`${output}/answer-${i+1}-${width}.png`});
   }
   const first=page.locator('.assistant-content').first().locator('.reference-button').first();
   const response=page.waitForResponse(r=>r.url().includes('/references/')&&r.request().method()==='GET');
   await first.click();const resolved=await response;assert.equal(resolved.status(),200);
   const target=await resolved.json();
   assert.equal(new URL(page.url()).searchParams.get('run'),target.run_id);
   await page.reload();
   if(width<1024)await page.getByRole('button',{name:'對話',exact:true}).click();
   await page.locator('.assistant-content').nth(count-1).waitFor();
   assert.deepEqual(errors,[]);
   checks.push({width,answers:count,rawReferencesHidden:true,referenceResolved:target,refreshPreserved:true,errors});
   await page.close();
  }
  fs.writeFileSync(`${output}/checks.json`,JSON.stringify(checks,null,2),{flag:'wx'});
  console.log(JSON.stringify(checks));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
module.exports=async function accessibilityQA(page,output){
 const focus=async locator=>{await locator.focus();assert.equal(await locator.evaluate(el=>el===document.activeElement),true);const outline=await locator.evaluate(el=>getComputedStyle(el).outlineStyle);assert.notEqual(outline,'none');};
 const separator=page.getByRole('separator');await focus(separator);await page.keyboard.press('End');assert.equal(await separator.getAttribute('aria-valuenow'),'480');await page.keyboard.press('Home');assert.equal(await separator.getAttribute('aria-valuenow'),'320');
 const overview=page.getByRole('tab',{name:'概覽',exact:true});await focus(overview);await page.keyboard.press('ArrowRight');assert.equal(await page.getByRole('tab',{name:'候選事件',exact:true}).getAttribute('aria-selected'),'true');
 const candidate=page.locator('[data-candidate-id]').first();await candidate.getByRole('button').press('Enter');
 const selectedId=await candidate.getAttribute('data-candidate-id');
 const version=page.getByLabel('檢視報告版本 v1');await focus(version);await page.keyboard.press('Enter');assert.equal(await page.locator('details').filter({has:version}).getAttribute('open'),'');await page.keyboard.press('Enter');assert.equal(await page.locator('details').filter({has:version}).getAttribute('open'),null);
 const exportLink=page.getByRole('link',{name:'匯出',exact:true});await focus(exportLink);
 const downloaded=page.waitForEvent('download');await page.keyboard.press('Enter');const file=await downloaded;assert.equal(await file.failure(),null);
 for(const width of [768,390]){
  await page.setViewportSize({width,height:900});
  await page.getByRole('button',{name:'對話',exact:true}).press('Enter');
  const draft='保留長中文草稿與事件條件：'+('極長事件名稱_不遺漏零事件用戶與未成熟用戶。').repeat(20);
  await page.getByLabel('分析草稿').fill(draft);
  await page.screenshot({path:path.join(output,`a11y-chat-${width}.png`)});
  await page.getByRole('button',{name:'結果',exact:true}).press('Enter');
  assert.equal(await page.getByRole('tab',{name:'候選事件',exact:true}).getAttribute('aria-selected'),'true');
  assert.equal(await page.getByRole('region',{name:'完整候選證據',exact:true}).getAttribute('data-selected-candidate'),selectedId);
  await page.getByRole('button',{name:'對話',exact:true}).press('Enter');assert.equal(await page.getByLabel('分析草稿').inputValue(),draft);
  await page.getByRole('button',{name:'結果',exact:true}).press('Enter');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.join(output,`a11y-results-${width}.png`)});
 }
 await page.setViewportSize({width:1440,height:900});
 const contrast=await page.evaluate(()=>{
  const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
  const lum=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
  return [...document.querySelectorAll('body *')].filter(el=>el.namespaceURI==='http://www.w3.org/1999/xhtml'&&[...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())&&el.getClientRects().length&&!el.closest(':disabled')).map(el=>{
   let parent=el,bg;while(parent){const c=rgb(getComputedStyle(parent).backgroundColor);if(c.length===3||c[3]===1){bg=c;break;}parent=parent.parentElement;}
   const fg=rgb(getComputedStyle(el).color),a=lum(fg),b=lum(bg||[16,17,20]);return {tag:el.tagName,text:el.textContent.slice(0,50),ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
  });
 });
 assert(contrast.length>10);assert.deepEqual(contrast.filter(c=>c.ratio<4.5),[]);
 const paletteContrast=await page.evaluate(()=>{
  const theme=getComputedStyle(document.documentElement);
  const l=hex=>{const rgb=hex.replace('#','').match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;};
  const colors=['--text','--muted','--accent'].map(k=>[k,theme.getPropertyValue(k).trim()]).concat([['error','#ffc0c0'],['warning','#e4ce9e'],['success','#b0d7b9'],['link','#a8afff']]);
  return colors.flatMap(([name,fg])=>['--background','--panel','--raised'].map(background=>{const a=l(fg),b=l(theme.getPropertyValue(background).trim());return {name,background,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};}));
 });
 assert.deepEqual(paletteContrast.filter(c=>c.ratio<4.5),[]);
 fs.writeFileSync(path.join(output,'a11y-checks.json'),JSON.stringify({contrast,paletteContrast,checks:['keyboard splitter','keyboard tabs','focus outlines','keyboard version disclosure','keyboard export download','768 and 390 selected candidate and draft retained','no page overflow']},null,2),{flag:'wx'});
 await overview.click();
 const empty=await page.context().browser().newPage({viewport:{width:390,height:844}});await empty.goto(new URL('/',page.url()).href);await empty.getByRole('heading',{name:'從一份用戶資料開始'}).waitFor();assert.equal(await empty.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await empty.screenshot({path:path.join(output,'a11y-empty.png')});await empty.close();
};

// Inlined into the offline reader; no network or executable model input.
const incomeGroups=data.income_groups;
const incomeSelect=el('income-group');
incomeGroups.forEach((g,i)=>{const o=node('option','起點後前 '+g.window_hours+' 小時 · '+g.ad_format);o.value=String(i);incomeSelect.append(o);});
function svgNode(tag,attributes,value){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attributes))n.setAttribute(k,String(v));if(value!==undefined)n.textContent=value;return n;}
function drawIncome(){
 const root=el('income-plots');root.replaceChildren();const group=incomeGroups[Number(incomeSelect.value)];
 if(!group){root.append(node('p','本匯出沒有已評估的單一累積收入候選。'));return;}
 const xs=group.points.map(p=>p.threshold_usd),minX=Math.min(...xs),maxX=Math.max(...xs);
 const x=v=>70+(maxX===minX?.5:(v-minX)/(maxX-minX))*500;
 for(const metric of ['coverage','difference_usd']){
  const title=metric==='coverage'?'覆蓋率（%）':'符合 − 未符合 D7 ARPU（USD）';root.append(node('h3',title));
  const known=group.points.filter(p=>p[metric]!==null);
  if(!known.length){root.append(node('p','沒有完整數值可繪製，未知不代表零。'));continue;}
  const vals=known.map(p=>p[metric]),lo=metric==='coverage'?0:Math.min(0,...vals),hi=metric==='coverage'?1:Math.max(0,...vals);
  const y=v=>210-(lo===hi?.5:(v-lo)/(hi-lo))*160;
  const label=v=>Number((metric==='coverage'?v*100:v).toPrecision(6)).toString();
  const svg=svgNode('svg',{viewBox:'0 0 640 270',role:'group','aria-label':title,'data-metric':metric,'data-x-min':minX,'data-x-max':maxX,style:'width:100%;min-height:180px'});
  for(const value of [lo,(lo+hi)/2,hi]){svg.append(svgNode('line',{x1:70,x2:570,y1:y(value),y2:y(value),stroke:'#454754'}),svgNode('text',{x:65,y:y(value)+4,'text-anchor':'end',fill:'currentColor','font-size':10},label(value)));}
  group.points.forEach((p,i)=>{const prev=group.points[i-1];if(p[metric]!==null&&prev?.[metric]!=null)svg.append(svgNode('line',{x1:x(prev.threshold_usd),x2:x(p.threshold_usd),y1:y(prev[metric]),y2:y(p[metric]),stroke:'#8b94e8'}));});
  for(const p of known){const circle=svgNode('circle',{cx:x(p.threshold_usd),cy:y(p[metric]),r:5,fill:'#8b94e8',tabindex:0,role:'button','data-candidate-id':p.candidate_id,'aria-label':p.threshold_usd+' USD；'+title+' '+label(p[metric])});
   circle.append(svgNode('title',{},p.threshold_usd+' USD；精確值 '+p[metric]+'；比較用戶 '+text(p.sample_size)));
   circle.onclick=()=>show(p.candidate_id);circle.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show(p.candidate_id);}};svg.append(circle);}
  svg.append(svgNode('text',{x:70,y:235,fill:'currentColor','font-size':11},minX+' USD'),svgNode('text',{x:570,y:235,'text-anchor':'end',fill:'currentColor','font-size':11},maxX+' USD'),svgNode('text',{x:320,y:260,'text-anchor':'middle',fill:'currentColor','font-size':12},'累積收入門檻（USD）'));root.append(svg);
 }
 const details=document.createElement('details');details.append(node('summary','全部圖點精確數值（含缺值）'));
 grid(details,'精確數值',['候選ID','收入門檻USD','覆蓋比例','D7差額USD','比較人數'],group.points.map(p=>[p.candidate_id,p.threshold_usd,p.coverage,p.difference_usd,p.sample_size]));root.append(details);
}
incomeSelect.oninput=drawIncome;drawIncome();

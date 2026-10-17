import {useEffect,useRef,useState} from 'react';
import * as echarts from 'echarts/core';
import {ScatterChart,LineChart,HeatmapChart} from 'echarts/charts';
import {GridComponent,TooltipComponent,VisualMapComponent} from 'echarts/components';
import {SVGRenderer} from 'echarts/renderers';
import {decodeChart,candidateColor,type Chart} from './chart-model';
import {displayNumber} from './report-language';
echarts.use([ScatterChart,LineChart,HeatmapChart,GridComponent,TooltipComponent,VisualMapComponent,SVGRenderer]);

export function ChartRenderer({input,runId,title,ids,labels=[],names={}}:{input:unknown;runId:string;title:string;ids:string[];labels?:string[];names?:Record<string,string>}){
  let chart:Chart;try{chart=decodeChart(input,runId);if(chart.chart_type==='heatmap'&&(labels.length>10||new Set(labels).size!==labels.length||chart.series.some(p=>p.x!>=labels.length||p.y!>=labels.length)))throw new Error('CHART_LABEL_MISMATCH');}catch(e){return <div role="alert">這張圖的資料未通過檢查，暫時無法顯示。<details><summary>技術詳情</summary>{e instanceof Error?e.message:'CHART_INVALID'}</details></div>;}
  return <ValidatedChart chart={chart} title={title} ids={ids} labels={labels} names={names}/>;
}
function ValidatedChart({chart,title,ids,labels,names}:{chart:Chart;title:string;ids:string[];labels:string[];names:Record<string,string>}){
  const root=useRef<HTMLDivElement>(null),[error,setError]=useState('');
  const usable=chart.series.filter(p=>p.x!==null&&p.y!==null&&(chart.chart_type!=='heatmap'||p.value!==null));
  useEffect(()=>{
    if(!root.current||!usable.length)return;
    const plot=echarts.init(root.current,undefined,{renderer:'svg'});setError('');
    const unit=(u:string)=>({percent:'符合比例（%）',USD:chart.chart_type==='scatter'?'平均廣告收益（美元）':'收益門檻（美元）',hours:'使用時間門檻（小時）',count:'次數門檻',candidate:'事件條件'}[u]||u);
    const tick=(v:number)=>v!==0&&(Math.abs(v)>=1e6||Math.abs(v)<.0001)?v.toExponential(2):String(v);
    const tipValue=(v:number|null,u:string)=>v===null?'未知':displayNumber(v,u==='percent'?'%':u==='USD'?'USD':'')+(u==='hours'?' 小時':u==='count'?' 次':'');
    const tooltip=(entry:{dataIndex:number})=>{
      const p=(chart.chart_type==='line'?chart.series:usable)[entry.dataIndex];if(!p)return '';
      if(chart.chart_type==='heatmap')return `${labels[p.x!]??'條件 A'} × ${labels[p.y!]??'條件 B'}\n人群相似度：${tipValue(p.value??null,'percent')}\n分母：至少符合其中一個條件的人數\n這張圖的分析人群：${chart.sample_size} 位用戶`;
      return `${names[p.candidate_id]||'事件條件'}\n${unit(chart.x_unit)}：${tipValue(p.x,chart.x_unit)}\n${unit(chart.y_unit)}：${tipValue(p.y,chart.y_unit)}\n符合比例的分母：${chart.sample_size} 位比較用戶\n精確值可展開下方數據表查閱`;
    };
    const css=getComputedStyle(root.current),color=(key:string)=>css.getPropertyValue(key).trim();
    const base={animation:false,textStyle:{color:color('--muted'),fontFamily:'system-ui'},grid:{left:70,right:30,top:45,bottom:80},
      tooltip:{backgroundColor:color('--panel'),borderColor:color('--line'),textStyle:{color:color('--text')},renderMode:'richText',confine:true,formatter:tooltip},xAxis:{type:'value',name:unit(chart.x_unit),nameLocation:'middle',nameGap:35,axisLabel:{color:color('--muted'),formatter:tick},splitLine:{lineStyle:{color:color('--line')}}},
      yAxis:{type:'value',name:unit(chart.y_unit),axisLabel:{color:color('--muted'),formatter:tick},splitLine:{lineStyle:{color:color('--line')}}}};
    const scale=(v:number|null,u:string)=>v===null?null:u==='percent'?v*100:v;
    try{
      if(chart.chart_type==='heatmap'){
        plot.setOption({...base,xAxis:{type:'category',data:labels,axisLabel:{color:color('--muted'),interval:0,rotate:45}},yAxis:{type:'category',data:labels,axisLabel:{color:color('--muted'),interval:0}},visualMap:{min:0,max:100,orient:'horizontal',left:'center',bottom:0,text:['100%','0%'],textStyle:{color:color('--muted')},inRange:{color:[color('--raised'),color('--accent')]}},series:[{type:'heatmap',data:usable.map(p=>[p.x,p.y,p.value!*100]),label:{show:false}}]});
      }else if(chart.chart_type==='scatter'){
        plot.setOption({...base,series:[{type:'scatter',symbolSize:12,data:usable.map(p=>({name:names[p.candidate_id]||'事件條件',value:[scale(p.x,chart.x_unit),scale(p.y,chart.y_unit)],itemStyle:{color:candidateColor(p.candidate_id,ids)}}))}]});
      }else{
        plot.setOption({...base,series:[{type:'line',connectNulls:false,smooth:false,lineStyle:{color:color('--accent')},data:chart.series.map(p=>({name:names[p.candidate_id]||'事件條件',value:[scale(p.x,chart.x_unit),scale(p.y,chart.y_unit)],itemStyle:{color:candidateColor(p.candidate_id,ids)}}))}]});
      }
    }catch(e){setError(e instanceof Error?e.message:'CHART_RENDER_FAILED');}
    const observer=new ResizeObserver(()=>plot.resize());observer.observe(root.current);
    return()=>{observer.disconnect();plot.dispose();};
  },[chart,ids,labels,names]);
  const axis=(u:string)=>({percent:'符合條件的比例',USD:chart.chart_type==='scatter'?'前 7 天平均廣告收益':'收益門檻',hours:'使用時間門檻',count:'次數門檻',candidate:'事件條件'}[u]||'數值');
  const number=(v:number|null,u:string)=>v===null?'未知':u==='candidate'?labels[v]??'未知條件':displayNumber(v,u==='percent'?'%':u==='hours'?'':u==='USD'?'USD':'')+(u==='hours'?' 小時':u==='count'?' 次':'');
  return <section className="chart-section" aria-label={title} data-chart-type={chart.chart_type} data-sample-size={chart.sample_size}><h3>{title}</h3><p>這張圖比較 {chart.sample_size} 位用戶。數據不足的點不會補成零；目前可顯示 {usable.length} / {chart.series.length} 個點。</p><p>{chart.chart_type==='heatmap'?'兩個條件都符合的人數，除以至少符合其中一個條件的人數。越接近 100%，選中的人群越相似；不代表收益較好。':chart.chart_type==='scatter'?'往右代表更多用戶符合，往上代表符合者過去的平均收益較高，不代表投放一定更有效。':'比較同一類條件，提高要求後，還有多少用戶符合。'}</p>
    {error&&<div role="alert"><p>目前無法繪製這張圖。你仍可展開下方數據表查看結果，或重新載入頁面再試。</p><details><summary>錯誤詳細資料</summary>{error}</details></div>}
    {usable.length?<div ref={root} role="img" aria-label={`${title}，完整數值見下方表格`} style={{height:340,width:'100%'}}/>:<p>沒有可繪製的完整數值，請查資料表及分析限制。</p>}
    <details><summary>圖表來源與計算狀態</summary><p className="dataset-identity">來源：{chart.artifact_id} · Run：{chart.run_id} · {chart.evidence_status}</p></details>
    <details><summary>查看圖表數據表</summary><div className="data-table" tabIndex={0} role="region" aria-label={`${title}數據表`}><table><thead><tr><th>候選</th><th>{axis(chart.x_unit)}</th><th>{axis(chart.y_unit)}</th>{chart.chart_type==='heatmap'&&<th>同時符合／至少符合一個</th>}</tr></thead><tbody>{chart.series.map((p,i)=><tr key={i} data-candidate-id={p.candidate_id}><td><span style={{color:candidateColor(p.candidate_id,ids)}}>● </span>{names[p.candidate_id]||'事件條件'}</td><td data-value={p.x??undefined} title={`原始值：${p.x??"未知"}`}>{number(p.x,chart.x_unit)}</td><td data-value={p.y??undefined} title={`原始值：${p.y??"未知"}`}>{number(p.y,chart.y_unit)}</td>{chart.chart_type==='heatmap'&&<td data-value={p.value??undefined} title={`原始值：${p.value??'未知'}`}>{p.value==null?'未知':displayNumber(p.value,'%')}</td>}</tr>)}</tbody></table></div></details>
  </section>;
}

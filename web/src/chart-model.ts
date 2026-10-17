// Restricted data contract, never an ECharts option supplied by a model.
export type Point={candidate_id:string;x:number|null;y:number|null;value?:number|null};
export type Chart={chart_type:'scatter'|'line'|'heatmap';artifact_id:string;run_id:string;x_unit:string;y_unit:string;sample_size:number;evidence_status:string;series:Point[]};
export function decodeChart(input:unknown,runId:string):Chart{
  const fail=():never=>{throw new Error('CHART_SCHEMA_INVALID');};
  if(!input||typeof input!=='object'||Array.isArray(input))fail();
  const c=input as Record<string,unknown>;
  const fields=['chart_type','artifact_id','run_id','x_unit','y_unit','sample_size','evidence_status','series'];
  if(Object.keys(c).some(k=>!fields.includes(k))||fields.some(k=>!(k in c)))fail();
  if(typeof c.chart_type!=='string'||!['scatter','line','heatmap'].includes(c.chart_type))fail();
  if(c.run_id!==runId)throw new Error('CHART_RUN_MISMATCH');
  for(const key of ['run_id','artifact_id'])if(typeof c[key]!=='string'||!c[key].length||c[key].length>256)fail();
  for(const key of ['x_unit','y_unit'])if(typeof c[key]!=='string'||!['percent','USD','hours','count','candidate'].includes(c[key]))fail();
  if(!Number.isSafeInteger(c.sample_size)||(c.sample_size as number)<0)fail();
  if(typeof c.evidence_status!=='string'||!['exploratory','insufficient_data','historically_validated'].includes(c.evidence_status))fail();
  if(!Array.isArray(c.series)||c.series.length>10000)fail();
  const cells=new Set<string>();
  if(c.chart_type==='heatmap'&&(c.x_unit!=='candidate'||c.y_unit!=='candidate'))fail();
  for(const p of c.series as unknown[]){
    if(!p||typeof p!=='object'||Array.isArray(p))fail();const q=p as Record<string,unknown>;
    if(Object.keys(q).some(k=>!['candidate_id','x','y','value'].includes(k)))fail();
    if(typeof q.candidate_id!=='string'||!q.candidate_id.length||q.candidate_id.length>256)fail();
    for(const k of ['x','y',...('value' in q?['value']:[])])if(q[k]!==null&&(typeof q[k]!=='number'||!Number.isFinite(q[k])))fail();
    if(c.chart_type==='heatmap'&&(!('value' in q)||!Number.isInteger(q.x)||!Number.isInteger(q.y)||(q.x as number)<0||(q.y as number)<0))fail();
    for(const axis of ['x','y'])if(c[`${axis}_unit`]==='percent'&&q[axis]!==null&&((q[axis] as number)<0||(q[axis] as number)>1))fail();
    if(c.chart_type==='heatmap'){
      if((q.x as number)>9||(q.y as number)>9||(q.value!==null&&((q.value as number)<0||(q.value as number)>1)))fail();
      const cell=`${q.x}:${q.y}`;if(cells.has(cell))fail();cells.add(cell);
    }
  }
  return input as Chart;
}

export const palette=['#5368a7','#287568','#996519','#95538d','#387cad','#ac5353','#747e32','#7960a6','#327d80','#916b43'];
export function candidateColor(id:string,ids:string[]){const i=ids.indexOf(id);if(i>=0)return palette[i%palette.length];let h=0;for(const c of id)h=(h*31+c.charCodeAt(0))>>>0;return palette[h%palette.length];}

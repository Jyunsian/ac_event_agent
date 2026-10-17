// Component-only synthetic fixture, excluded from the production build entry.
import React from 'react';
import {createRoot} from 'react-dom/client';
import {ChartRenderer} from '../src/chart-renderer';
import '../src/style.css';
const base={artifact_id:'synthetic-boundary-fixture',run_id:'synthetic',x_unit:'percent',y_unit:'USD',sample_size:100,evidence_status:'exploratory'};
const scatter={...base,chart_type:'scatter',series:[{candidate_id:'極長中文廣告事件名稱_'.repeat(12),x:0,y:0},{candidate_id:'small',x:.1,y:.000001},{candidate_id:'large',x:1,y:1e12},{candidate_id:'unknown',x:.4,y:null}]};
const line={...base,chart_type:'line',x_unit:'hours',series:[{candidate_id:'a',x:1,y:1},{candidate_id:'b',x:2,y:null},{candidate_id:'c',x:3,y:3}]};
const heat={...base,chart_type:'heatmap',x_unit:'candidate',y_unit:'candidate',series:[{candidate_id:'a',x:0,y:0,value:1},{candidate_id:'a',x:0,y:1,value:null},{candidate_id:'b',x:1,y:0,value:0},{candidate_id:'b',x:1,y:1,value:1}]};
createRoot(document.getElementById('root')!).render(<main style={{maxWidth:960,padding:16,margin:'auto'}}><h1>合成圖表邊界測試 · 非客戶資料</h1>
  <ChartRenderer input={scatter} runId="synthetic" title="非空散點與極值" ids={['zero','small','large','unknown']} names={Object.fromEntries(scatter.series.map(p=>[p.candidate_id,p.candidate_id]))}/>
  <ChartRenderer input={line} runId="synthetic" title="折線缺值" ids={['a','b','c']}/>
  <ChartRenderer input={heat} runId="synthetic" title="重疊零值與未知" ids={['a','b']} labels={['C1','C2']}/>
  <ChartRenderer input={{...scatter,chart_type:'html'}} runId="synthetic" title="拒絕非法類型" ids={[]}/>
</main>);

import test from 'node:test';
import assert from 'node:assert/strict';
import {decodeChart} from '../web/src/chart-model.ts';
const chart=()=>({chart_type:'scatter',artifact_id:'validation:hash',run_id:'run',x_unit:'percent',y_unit:'USD',sample_size:2,evidence_status:'exploratory',series:[{candidate_id:'c',x:0,y:null}]});
test('null and zero remain distinct; reject executable options and unbounded payloads',()=>{
 assert.equal(decodeChart(chart(),'run').series[0].y,null);
 for(const patch of [{chart_type:'html'},{tooltip:{formatter:'alert(1)'}},{series:Array(10001).fill(chart().series[0])},{sample_size:-1},{series:[{candidate_id:'c',x:Infinity,y:0}]}])assert.throws(()=>decodeChart({...chart(),...patch},'run'),/CHART_SCHEMA_INVALID/);
 assert.throws(()=>decodeChart(chart(),'other'),/CHART_RUN_MISMATCH/);
 for(const patch of [{chart_type:['scatter']},{x_unit:['percent']},{evidence_status:['exploratory']}])assert.throws(()=>decodeChart({...chart(),...patch},'run'),/SCHEMA_INVALID/);
});
test('heatmap rejects out-of-domain ratios, coordinates and duplicate cells',()=>{
 const heat={...chart(),chart_type:'heatmap',x_unit:'candidate',y_unit:'candidate',series:[{candidate_id:'c',x:0,y:0,value:null}]};
 assert.equal(decodeChart(heat,'run').series[0].value,null);
 for(const point of [{x:10},{y:.5},{value:1.1},{value:-.01}])assert.throws(()=>decodeChart({...heat,series:[{...heat.series[0],...point}]},'run'),/SCHEMA_INVALID/);
 assert.throws(()=>decodeChart({...heat,series:[heat.series[0],heat.series[0]]},'run'),/SCHEMA_INVALID/);
 assert.throws(()=>decodeChart({...chart(),series:[{candidate_id:'c',x:1.01,y:3}]},'run'),/SCHEMA_INVALID/);
 assert.equal(decodeChart({...chart(),series:[{candidate_id:'c',x:1,y:1e12}]},'run').series[0].y,1e12);
});

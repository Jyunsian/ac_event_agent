import test from 'node:test';
import assert from 'node:assert/strict';
import {sortPriority} from '../web/src/priority-sort.ts';
test('priority sorting preserves frozen order, nulls, negative differences and v1 semantics',()=>{
  const row=(id,difference,arpu,coverage,speed)=>({candidate_id:id,metrics:{comparisons:{triggered_minus_untriggered:difference},groups:{triggered:{arpu_usd:arpu}},coverage,delay_seconds:{p90:speed}}});
  const rows=[row('z',null,100,null,null),row('b',-2,8,.8,50),row('a',-1,3,.8,100)];
  const snapshot=structuredClone(rows),ids=(sort,v2=true)=>sortPriority(rows,sort,v2).map(r=>r.candidate_id);
  assert.deepEqual(ids('original'),['z','b','a']);
  assert.deepEqual(ids('revenue'),['a','b','z']);
  assert.deepEqual(ids('revenue',false),['z','b','a']);
  assert.deepEqual(ids('coverage'),['a','b','z']);
  assert.deepEqual(ids('speed'),['b','a','z']);
  assert.deepEqual(rows,snapshot);assert.notEqual(sortPriority(rows,'original',true),rows);
});

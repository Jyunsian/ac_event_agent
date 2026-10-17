import test from 'node:test';
import assert from 'node:assert/strict';
import {errorText,runStatus,stageLabel,fileSize,dateText} from '../web/src/language.ts';
import {fieldCopy,utcInput,utcValue} from '../web/src/field-language.ts';
import {readFileSync} from 'node:fs';
import {candidateName,conditionName,duration} from '../web/src/candidate-language.ts';
import {displayNumber,reasonsText} from '../web/src/report-language.ts';
test('report presentation retains tiny nonzero amounts and explains limitations without exposing codes',()=>{
  assert.equal(displayNumber(0,'USD'),'0 美元');
  assert.notEqual(displayNumber(0.00000001,'USD'),'0 美元');
  assert.equal(displayNumber(5400,'h'),'1.5 小時');
  assert.equal(displayNumber(.25,'%'),'25%');
  assert.match(reasonsText(['INSUFFICIENT_GROUP_USERS']),/用戶太少/);
  assert.doesNotMatch(reasonsText(['UNKNOWN_PRIVATE_CODE']),/UNKNOWN_PRIVATE_CODE/);
  assert.match(reasonsText(['FOLLOWUP_IS_EXPLORATORY']),/新資料確認/);
});
test('candidate names preserve operator, origin, thresholds, format and sequence constraints',()=>{
  assert.equal(candidateName({origin:'first_open',window_hours:3,predicate:{op:'count',threshold:5,ad_format:'rewarded'}}),'首次開啟 App後 3 小時內，看過獎勵式廣告至少 5 次');
  const clauses=[{op:'session_count',threshold:2},{op:'revenue_sum',threshold:0.000001}];
  assert.match(conditionName({op:'and',clauses}),/而且/);assert.match(conditionName({op:'or',clauses}),/或者/);
  assert.match(conditionName(clauses[1]),/\$0\.000001/);
  assert.match(conditionName({op:'sequence',steps:['session_start','ad_impression'],max_gap_seconds:120,repeats:2}),/2 分鐘，至少出現 2 次/);
  assert.equal(duration(5400),'1 小時 30 分鐘');
  assert.equal(candidateName({origin:'install',window_hours:3,predicate:{node:'atom',metric:'level_time_to_reach_seconds',comparator:'gte',threshold:10216.99,scope:{level_index:3}}}),'安裝後，超過 2 小時 50 分鐘才到達第 3 關（只觀察前 3 小時）');
  assert.equal(candidateName({origin:'install',window_hours:48,predicate:{node:'atom',metric:'level_time_to_reach_seconds',comparator:'lte',threshold:141458.63,scope:{level_index:8}}}),'安裝後 39 小時 18 分鐘內到達第 8 關');
  assert.equal(conditionName({node:'atom',metric:'complete_start_ratio',comparator:'gte',threshold:.75,scope:{}}),'開始的關卡中，至少 75% 有完成');
  assert.equal(conditionName({node:'atom',metric:'return_in_interval',comparator:'gte',threshold:1,scope:{start_hours:24,end_hours:48}}),'在安裝後第 24～48 小時期間回來使用 App');
});
test('every V3 event family has a plain-language deterministic description',()=>{
  const metrics=['ad_count','ad_revenue_sum','session_count','first_return_delay_seconds','return_in_interval','return_interval_count','consecutive_return_days','post_return_session_count','post_return_engaged_seconds','level_start_count','level_complete_count','level_fail_count','distinct_completed_levels','max_completed_level_index','completed_level','reached_level','level_time_to_reach_seconds','attempts_per_level','completes_per_session','complete_start_ratio','fail_start_ratio','completion_duration_seconds','consecutive_failures','retry_same_level','complete_after_fail','session_after_fail'];
  for(const metric of metrics){
    const scope=metric==='level_time_to_reach_seconds'?{level_index:3}:metric==='return_in_interval'?{start_hours:24,end_hours:48}:metric.startsWith('ad_')?{ad_format:'rewarded'}:{};
    const name=conditionName({node:'atom',metric,comparator:'gte',threshold:metric.endsWith('_ratio')?.75:metric.includes('seconds')?10216.99:3,scope});
    assert.doesNotMatch(name,/其他玩家行為|指定關卡|[_]/,metric);
  }
  for(const template of ['level_start_to_complete','level_fail_to_start','level_fail_to_complete','level_fail_to_session_end','session_start_to_level_complete','level_complete_to_ad_impression','rewarded_ad_to_level_complete']){
    const name=conditionName({node:'sequence',template,max_gap_seconds:1800,repeats:1});
    assert.doesNotMatch(name,/指定行為|[_]/,template);
  }
});
test('every supported source field has a human label and UTC roundtrips without timezone shifts',()=>{
  const schema=JSON.parse(readFileSync(new URL('../contracts/schema.json',import.meta.url)));
  for(const role of ['user','event'])for(const key of Object.keys(schema.$defs[role].properties)){
    assert.ok(fieldCopy[key]?.label,key);assert.ok(fieldCopy[key]?.help,key);
  }
  for(const value of ['2026-01-14T00:00:00Z','2026-01-14T12:34:56.123Z',''])assert.equal(utcValue(utcInput(value)),value);
  assert.equal(utcInput('2026-01-14T08:00:00+08:00'),'');
});
test('unknown errors never expose raw server content or claim success',()=>{
  assert.equal(errorText(new Error('secret arbitrary server body')),errorText('UNRECOGNIZED'));
  assert.doesNotMatch(errorText('AGENT_TIMEOUT'),/AGENT_TIMEOUT|Worker/);
  assert.match(errorText('FILE_FINGERPRINT_MISMATCH'),/原本/);
});
test('display units and stages do not alter domain values',()=>{
  assert.equal(fileSize(1024),'1.0 KB');
  assert.equal(fileSize(0),'0 B');
  assert.equal(fileSize(NaN),'大小未知');
  assert.match(dateText('2026-01-14T00:00:00Z'),/UTC/);
  assert.equal(dateText('invalid'),'時間未知');
  assert.equal(runStatus.queued,'等待開始分析');
  assert.equal(Object.keys(stageLabel).length,12);
});

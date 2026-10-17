import test from 'node:test';
import assert from 'node:assert/strict';
import {incomeComparison,evidenceLabel,difference,overviewPoint,deadlineLabel,reportTotals} from '../web/src/v4-presentation.ts';
test('V4 separates exploratory, untested, insufficient and supported evidence',()=>{
 assert.equal(evidenceLabel({claim_allowed:true},true),'僅供探索');
 assert.equal(evidenceLabel(undefined),'尚未驗證');
 assert.equal(evidenceLabel({testable:false}),'資料不足');
 assert.equal(evidenceLabel({testable:true,claim_allowed:false}),'收入較高：未確認');
 assert.equal(evidenceLabel({claim_allowed:true}),'收入較高：已驗證');
 assert.equal(difference(null,0),null);assert.equal(difference(.8,.9),.8-.9);
});
test('V4 stays at selected clock and distinguishes rolling from cumulative',()=>{
 const row={time_analysis:{observation:[{hours:24,coverage:.1},{hours:48,coverage:.2}],inference:[{hours:24,claim_allowed:true},{hours:48,claim_allowed:false}],controls:{'48':{observation:{coverage:.19},rule:{predicate:{threshold:.02}}}}},event_spec:{mode:'cumulative'}};
 const point=overviewPoint(row,48);assert.equal(point.point.coverage,.2);assert.equal(point.control.coverage,.19);assert.equal(point.tests[0].claim_allowed,false);assert.equal(point.threshold,.02);
 assert.match(deadlineLabel({mode:'rolling',origin:'install'},48),/48 小時，曾在連續 24/);
 assert.match(deadlineLabel({mode:'snapshot'},48),/指定時間判斷/);
 assert.match(deadlineLabel({mode:'cumulative',origin:'first_open'},24),/首次開啟後/);
});

test('three cohorts never fall back to all-player numbers',()=>{
 const row={time_analysis:{observation:[{hours:24,coverage:.2}],exploration:[{hours:24,coverage:.3}],holdout:[{hours:24,coverage:.1}]}};
 assert.equal(overviewPoint(row,24,'exploration').point.coverage,.3);
 assert.equal(overviewPoint(row,24,'holdout').point.coverage,.1);
 delete row.time_analysis.exploration;assert.equal(overviewPoint(row,24,'exploration').point,undefined);
});

test('income comparisons name direction and retain unknown and small differences',()=>{
 assert.equal(incomeComparison(.98,'未符合玩家'),'比未符合玩家高 $0.98／人');
 assert.equal(incomeComparison(-.1,'收入門檻玩家'),'比收入門檻玩家低 $0.10／人');
 assert.equal(incomeComparison(0,'收入門檻玩家'),'與收入門檻玩家相同');
 assert.equal(incomeComparison(null,'未符合玩家'),'與未符合玩家無法比較');
 assert.match(incomeComparison(-.001,'未符合玩家'),/低 不到/);
});

test('overview totals work without candidates and never fill unknown revenue with zero',()=>{
 const r={candidates:[],summary:{targets:{mature_users:10,summary:{exploration:{users:7,revenue_usd:14,unknown_targets:0},holdout:{users:3,revenue_usd:9,unknown_targets:0}}}}};
 assert.deepEqual(reportTotals(r),{revenue_usd:23,arpu_usd:2.3});
 r.summary.targets.summary.holdout.unknown_targets=1;
 assert.deepEqual(reportTotals(r),{revenue_usd:null,arpu_usd:null});
 r.summary.targets.summary.holdout.unknown_targets=0;r.summary.targets.mature_users=11;
 assert.deepEqual(reportTotals(r),{revenue_usd:null,arpu_usd:null});
});

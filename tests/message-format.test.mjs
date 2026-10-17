import test from 'node:test';
import assert from 'node:assert/strict';
import {messageBlocks,inlineParts,tableCells} from '../web/src/message-format.ts';
test('comparison tables preserve small numbers, escaped pipes, and unknown values',()=>{
  const blocks=messageBlocks('| 條件 | 收益 |\n| --- | ---: |\n| A\\|B | 0.00000001 美元 |\n| C | 未知 |');
  assert.equal(blocks[0].kind,'table');assert.equal(blocks[0].lines.length,3);
  assert.deepEqual(tableCells(blocks[0].lines[1]),['A|B','0.00000001 美元']);
  assert.equal(tableCells(blocks[0].lines[2])[1],'未知');
});
import {referenceBinding} from '../web/src/message-references.ts';
test('references require same-turn completed receipts and unambiguous persisted versions',()=>{
  const id='report:00000000-0000-0000-0000-000000000001#/summary';
  const event={turn_id:'turn',kind:'tool_completed',payload:{run_id:'source',report_version:2,references:[{evidence_id:id,run_id:'source'}]}};
  assert.deepEqual(referenceBinding([event],'turn',id),{selected_run_id:'source',selected_candidate_id:null,report_version:2});
  assert.equal(referenceBinding([event],'other',id),null);
  assert.equal(referenceBinding([{...event,kind:'tool_failed'}],'turn',id),null);
  assert.equal(referenceBinding([event],'turn',id+'invented'),null);
  const conflict={...event,payload:{...event.payload,report_version:3}};
  assert.equal(referenceBinding([event,conflict],'turn',id),null);
  const explicit={...event,payload:{...event.payload,references:[{evidence_id:id,run_id:'historical',report_version:1}]}};
  assert.equal(referenceBinding([explicit],'turn',id).selected_run_id,'historical');
  const legacy={...event,payload:{references:event.payload.references}};
  const user={turn_id:'turn',kind:'message_created',payload:{role:'user',context:{selected_run_id:'source',report_version:2}}};
  assert.equal(referenceBinding([user,legacy],'turn',id).report_version,2);
  assert.equal(referenceBinding([legacy],'turn',id),null);
  const earlier={...event,seq:2};
  assert.equal(referenceBinding([earlier],'followup',id,4).report_version,2);
  assert.equal(referenceBinding([{...earlier,seq:5}],'followup',id,4),null);
  assert.equal(referenceBinding([event],'followup',id,4),null);
});
test('message blocks preserve content and readable structure without interpreting HTML',()=>{
  const blocks=messageBlocks('# 結論\n\n可以比較\n但樣本少\n\n- 第一項\n- 第二項\n\n```html\n<script>alert(1)</script>\n```');
  assert.deepEqual(blocks.map(b=>b.kind),['heading','paragraph','list','code']);
  assert.equal(blocks[3].lines[0],'<script>alert(1)</script>');
  assert.equal(messageBlocks('```\n未關閉的程式區塊')[0].lines[0],'未關閉的程式區塊');
});
test('inline citations preserve exact reference, formatting is text only, links not executable',()=>{
  const ref='report:123#/candidates/0';
  assert.deepEqual(inlineParts(`[來源](${ref})`),[{kind:'reference',text:ref}]);
  assert.deepEqual(inlineParts(`${ref}.`),[{kind:'reference',text:ref},{kind:'text',text:'.'}]);
  assert.deepEqual(inlineParts(`（${ref}、${ref}）`).filter(p=>p.kind==='reference').map(p=>p.text),[ref,ref]);
  assert.deepEqual(inlineParts('**結論** `0.00001`'),[{kind:'strong',text:'結論'},{kind:'text',text:' '},{kind:'code',text:'0.00001'}]);
  assert.equal(inlineParts('[按我](javascript:alert(1))')[0].kind,'text');
});

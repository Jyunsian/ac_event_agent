// Explicitly requested live-model check against an already configured local Worker.
// Only use a known synthetic baseline. No key is read or printed by this script.
import fs from 'node:fs';
import {randomUUID,createHash} from 'node:crypto';
const [base,run,directory]=process.argv.slice(2);
if(!base||!run||!directory)throw Error('Usage: BASE SYNTHETIC_RUN NEW_OUTPUT_DIRECTORY');
const endpoint=new URL(base);
if(endpoint.hostname!=='127.0.0.1')throw Error('Local synthetic check only');
async function request(route,body){
 const response=await fetch(base+route,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','Idempotency-Key':randomUUID()}:{},body:body?JSON.stringify(body):undefined});
 if(!response.ok)throw Error(`HTTP ${response.status} at ${route}`);
 return response.json();
}
const report=await request(`/api/runs/${run}/reports/1/json`);
if(!report.synthetic&&!report.audit?.synthetic&&!report.summary?.synthetic)throw Error('Refuse baseline without synthetic marker');
fs.mkdirSync(directory,{recursive:false,mode:0o700});
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const before=hash(report);
const conversation=await request(`/api/runs/${run}/conversations`,{});
const results=[];
try{
 const questions=['請先讀取這份基礎報告，說明候選與限制，引用實際證據。','請建立只看安裝後前3小時的分析分支，等待Python計算完成，再引用新結果說明與原報告的差異。請在300字內簡述。'];
 const languageQuestions=[
  '這份資料有值得先測試的廣告事件嗎？請用一般App開發者聽得懂的話，引用資料說明原因與限制。',
  '請分析開始使用後前3小時的事件，等結果完成後，說明和原本結果有哪些差異。請勿把候選組合也改變的比較說成只有時間的影響。',
  '請只看美國用戶，和整體結果比較；如果人數太少，請直說不能判斷。',
  '原本這份報告中的候選事件，選到的是同一群人嗎？請先讀現有的人群重疊結果，不要重新分析。',
  '為什麼這份資料還不能直接給投放建議？我下一步最需要補什麼？只解釋現有結果，不要重跑。',
 ];
 const finalLanguageQuestion='我不懂統計。請用白話、200字以內說明這份資料為什麼還不能給投放建議，以及我最需要補什麼。只讀現有結果，不要重跑；請附可以查閱的證據。';
 for(const content of process.argv.includes('--language-final')?[finalLanguageQuestion]:process.argv.includes('--language')?languageQuestions:process.argv.includes('--branch-only')?questions.slice(1):questions){
  const sent=await request(`/api/conversations/${conversation.id}/messages`,{content,selected_run_id:run});
  console.log(JSON.stringify({conversation:conversation.id,turn:sent.turn_id,status:'submitted'}));
  const deadline=Date.now()+360000;let turn;
  for(;;){
   const state=await request(`/api/conversations/${conversation.id}`);
   turn=state.turns.find(t=>t.id===sent.turn_id);
   if(turn&&['succeeded','failed','cancelled'].includes(turn.status))break;
   if(Date.now()>deadline)throw Error('Observation deadline; inspect existing turn before retrying');
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
  const events=[];let after=0;
  for(;;){const page=await request(`/api/conversations/${conversation.id}/events?after=${after}&limit=200`);events.push(...page.events);if(!page.has_more)break;after=page.next_after;}
  results.push({content,turn,events});
  fs.writeFileSync(directory+'/progress.json',JSON.stringify({synthetic:true,model:'z-ai/glm-5.3-flash',conversation:conversation.id,results},null,2),{mode:0o600});
  if(turn.status!=='succeeded')throw Error('Live turn '+turn.status+': '+JSON.stringify(turn.error));
 }
 if(hash(await request(`/api/runs/${run}/reports/1/json`))!==before)throw Error('Parent changed');
 fs.writeFileSync(directory+'/result.json',JSON.stringify({status:'passed',synthetic:true,model:'z-ai/glm-5.3-flash',conversation:conversation.id,parent:run,parentUnchanged:true,results},null,2),{flag:'wx',mode:0o600});
 console.log(JSON.stringify({status:'passed',conversation:conversation.id,directory}));
}catch(error){
 fs.writeFileSync(directory+'/failure.json',JSON.stringify({status:'failed',conversation:conversation.id,error:error.message}),{mode:0o600});
 console.error(error.message);process.exitCode=1;
}

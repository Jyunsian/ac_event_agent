// Test-only harness: real production worker/HTTP/SDK with a deterministic model.
import {createServer} from 'node:http';
import {MockLanguageModelV4} from 'ai/test';
import {AgentWorker} from './dist/worker.js';
const usage={inputTokens:{total:10,noCache:10,cacheRead:0,cacheWrite:0},outputTokens:{total:5,text:5,reasoning:0}};
const response=(content,reason='stop')=>({content,finishReason:{unified:reason,raw:reason},usage,warnings:[]});
const failed=new Set();
const model=new MockLanguageModelV4({doGenerate:async({prompt,abortSignal})=>{
  const question=prompt.filter(m=>m.role==='user').map(m=>JSON.stringify(m.content)).filter(m=>!m.includes('目前介面引用')).at(-1)||'';
  if(question.includes('[fail]')&&!failed.has(question)){failed.add(question);throw new Error('synthetic provider failure');}
  if(question.includes('[slow]'))await new Promise((resolve,reject)=>{
    const timer=setTimeout(resolve,8000);
    abortSignal.addEventListener('abort',()=>{clearTimeout(timer);reject(abortSignal.reason);},{once:true});
  });
  const previous=prompt.filter(m=>m.role==='tool').at(-1);
  if(!previous)return response([{type:'tool-call',toolCallId:'browser-read',toolName:'get_baseline_report',input:'{}'}],'tool-calls');
  const evidence=previous.content[0].output.value;
  const long=question.includes('[long]')?'這是合成測試模型的長中文回覆，用於驗證閱讀和換行；不代表真實模型或投放成效。\n'.repeat(60):'歷史相關性不代表投放提升。';
  return response([{type:'text',text:`合成測試模型：${long} ${evidence.references[0].evidence_id}`}]);
}});
const shutdown=new AbortController();
const worker=new AgentWorker({baseUrl:process.argv[2],token:process.env.AGENT_INTERNAL_TOKEN,heartbeatMs:100},model);
const server=createServer((req,res)=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({service:'agent',status:'alive',provider:{available:true},workerConnected:worker.connected,synthetic:true}));});
server.listen(0,'127.0.0.1',()=>console.log(`http://127.0.0.1:${server.address().port}/health`));
void worker.run(shutdown.signal);
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{shutdown.abort();server.close();});

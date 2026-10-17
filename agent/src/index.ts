import { createServer } from 'node:http';
import {providerStatus} from './runtime.js';
import {AgentWorker} from './worker.js';
const port=Number(process.env.AGENT_PORT ?? 8081);
const shutdown=new AbortController();
const timeoutMs=Number(process.env.AGENT_TIMEOUT_MS??120000);
if(!Number.isInteger(timeoutMs)||timeoutMs<1000||timeoutMs>600000)throw new Error('INVALID_AGENT_TIMEOUT_MS');
const worker=process.env.AGENT_INTERNAL_TOKEN?.trim()&&process.env.AGENT_API_BASE_URL?.trim()?
  new AgentWorker({baseUrl:process.env.AGENT_API_BASE_URL,token:process.env.AGENT_INTERNAL_TOKEN,runtimeLimits:{timeoutMs}}):null;
const running=worker?.run(shutdown.signal);
const server=createServer((req,res)=>{
  res.setHeader('Content-Type','application/json; charset=utf-8');
  if(req.url==='/health'){
    res.end(JSON.stringify({service:'agent',status:'alive',runtimeReady:true,provider:providerStatus(),workerConnected:worker?.connected??false}));
  }else{res.statusCode=404;res.end(JSON.stringify({error_code:'NOT_FOUND'}));}
});
server.listen(port,process.env.AGENT_HOST ?? '127.0.0.1',()=>console.log('Agent process listening on '+port));
for(const signal of ['SIGTERM','SIGINT'] as const)process.on(signal,()=>{shutdown.abort();server.close();void running;});

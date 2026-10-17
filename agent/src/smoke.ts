// Explicit opt-in: synthetic content only, but this invokes a paid remote model.
import {tool} from 'ai';
import {z} from 'zod';
import {runAgent} from './runtime.js';
if(!process.argv.includes('--allow-paid')){
  console.error('Requires --allow-paid plus server OPENROUTER_API_KEY and OPENROUTER_MODEL. Synthetic input only.');process.exitCode=2;
}else{
  const seen:number[]=[];
  try{
    const result=await runAgent({messages:[{role:'user',content:'Synthetic integration smoke. First call evidence with n=1. Read its result, then call evidence with n=2. Finally summarize both and cite their synthetic artifact IDs. Do not skip calls.'}],tools:{evidence:tool({description:'Read synthetic smoke evidence; n=2 is allowed only after n=1.',inputSchema:z.object({n:z.enum(['1','2'])}),execute:async({n})=>{
      if(n==='2'&&!seen.includes(1))throw new Error('SMOKE_ORDER_INVALID');seen.push(Number(n));return {synthetic:true,artifact_id:`smoke-${n}`,value:Number(n)*2};
    }})},maxSteps:5});
    if(!seen.includes(1)||!seen.includes(2)||result.steps.length<3||result.status!=='completed')throw new Error('SMOKE_TWO_ROUNDS_REQUIRED');
    console.log(JSON.stringify({synthetic:true,status:'passed',steps:result.steps.length,toolCalls:seen,usage:result.usage}));
  }catch{console.error('OPENROUTER_SMOKE_FAILED');process.exitCode=1;}
}

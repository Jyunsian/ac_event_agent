// Explicitly authorized cleanup of old synthetic test Worker work databases.
// Source files, published artifacts, reports and the Worker root are never deleted.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const workspace=fs.realpathSync(process.cwd());
if(workspace!=='/Users/jj/Desktop/ac_event_agent')throw Error('WRONG_WORKSPACE');
const root=fs.realpathSync('/var/folders/7n/_7cv6mz153xc8cnry998gskc0000gn/T/ac-event-work');
const runtime=path.join(workspace,'.runtime');
const names=new Set(['work.duckdb','scope.duckdb']);
function assertIdle(){
 const lines=execFileSync('ps',['-axo','comm=,args='],{encoding:'utf8'}).split('\n');
 if(lines.some(line=>/^\S*python(?:\d+(?:\.\d+)*)?\s/.test(line.trim())&&
     (line.includes('spawn_main')||line.includes('pytest'))))throw Error('ANALYSIS_OR_TEST_ACTIVE');
}
function eligible(file){
 const relative=path.relative(root,file),parts=relative.split(path.sep);
 if(parts.length<3||!/^ac-baseline-[a-z0-9_]+$/.test(parts[0])||
    !names.has(path.basename(file))||fs.realpathSync(file)!==file)return false;
 const stat=fs.statSync(file);
 if(!stat.isFile()||Date.now()-stat.mtimeMs<3600000||
    Date.now()-fs.statSync(path.join(root,parts[0])).mtimeMs<3600000)return false;
 const manifest=path.join(path.dirname(file),'manifest.json');
 if(!fs.existsSync(manifest)||fs.lstatSync(manifest).isSymbolicLink())return false;
 const data=JSON.parse(fs.readFileSync(manifest,'utf8'));
 return data.synthetic===true&&!(data.artifacts??[]).some(a=>a.path===path.basename(file));
}
assertIdle();
if(process.argv[2]==='--apply'){
 const planPath=path.resolve(process.argv[3]??'');
 if(path.dirname(planPath)!==runtime||!/^worker-scratch-cleanup-\d+\.json$/.test(path.basename(planPath)))throw Error('INVALID_PLAN');
 const plan=JSON.parse(fs.readFileSync(planPath,'utf8'));
 if(plan.workspace!==workspace||plan.root!==root||plan.status!=='inventory')throw Error('INVALID_PLAN');
 for(const item of plan.targets)if(!eligible(item.file)||fs.statSync(item.file).size!==item.bytes||
    fs.statSync(item.file).mtimeMs!==item.mtime)throw Error('TARGET_CHANGED');
 assertIdle();
 for(const item of plan.targets)fs.unlinkSync(item.file);
 const result={status:'removed',targets:plan.targets,reclaimed_bytes:plan.targets.reduce((s,x)=>s+x.bytes,0),
  retained:'all input, manifests, Parquet, reports, service data and uncompleted stages'};
 fs.writeFileSync(planPath.replace('.json','-result.json'),JSON.stringify(result,null,2),{flag:'wx',mode:0o600});
 console.log(JSON.stringify({status:result.status,count:plan.targets.length,reclaimed_bytes:result.reclaimed_bytes}));
}else{
 const targets=[];
 function walk(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
  const file=path.join(dir,entry.name);
  if(entry.isSymbolicLink())continue;
  if(entry.isDirectory())walk(file);
  else if(names.has(entry.name)&&eligible(file)){const stat=fs.statSync(file);targets.push({file,bytes:stat.size,mtime:stat.mtimeMs});}
 }}
 for(const entry of fs.readdirSync(root,{withFileTypes:true}))if(entry.isDirectory()&&/^ac-baseline-[a-z0-9_]+$/.test(entry.name))walk(path.join(root,entry.name));
 const planPath=path.join(runtime,`worker-scratch-cleanup-${Date.now()}.json`);
 fs.writeFileSync(planPath,JSON.stringify({workspace,root,status:'inventory',targets},null,2),{flag:'wx',mode:0o600});
 console.log(JSON.stringify({manifest:planPath,count:targets.length,bytes:targets.reduce((s,x)=>s+x.bytes,0)}));
}

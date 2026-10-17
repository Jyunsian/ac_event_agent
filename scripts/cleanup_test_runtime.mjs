// Explicit user-authorized cleanup of stopped, unreferenced synthetic test service directories.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const workspace=fs.realpathSync(process.cwd());
const root=fs.realpathSync(path.join(workspace,'.runtime'));
if(workspace!=='/Users/jj/Desktop/ac_event_agent'||root!==path.join(workspace,'.runtime'))throw Error('WRONG_WORKSPACE');
const pattern=/^(pg-test-|s3-test-)[a-zA-Z0-9_-]+$/;
// Explicit opt-in during long local test suites; process/reference/newest guards
// still apply. Never use a zero-age window for just-created test services.
const minimumAgeMs=process.argv.includes('--recent-stopped')?5*60*1000:60*60*1000;
const referenced=new Set();
function readReferences(file){
  for(const name of fs.readFileSync(file,'utf8').match(/(?:pg-test-|s3-test-)[a-zA-Z0-9_-]+/g)??[])referenced.add(name);
}
for(const dir of [workspace,path.join(workspace,'docs'),path.join(workspace,'evidence')]){
  for(const item of fs.readdirSync(dir,{withFileTypes:true}))if(item.isFile()&&item.name.endsWith('.md'))readReferences(path.join(dir,item.name));
}
function resultReferences(dir){
  for(const item of fs.readdirSync(dir,{withFileTypes:true})){
    if(item.isSymbolicLink())continue;
    if(item.isFile()&&item.name==='result.json')readReferences(path.join(dir,item.name));
    if(item.isDirectory()&&!pattern.test(item.name)&&!['bin','work','source','node_modules','.venv','data'].includes(item.name))resultReferences(path.join(dir,item.name));
  }
}
resultReferences(root);
const directories=fs.readdirSync(root,{withFileTypes:true}).filter(x=>x.isDirectory()&&pattern.test(x.name))
  .map(x=>({name:x.name,path:path.join(root,x.name),mtime:fs.statSync(path.join(root,x.name)).mtimeMs}));
const newest=new Set();
for(const prefix of ['pg-test-','s3-test-'])for(const item of directories.filter(x=>x.name.startsWith(prefix)).sort((a,b)=>b.mtime-a.mtime).slice(0,10))newest.add(item.name);
function safe(item,processes){
  if(path.dirname(item.path)!==root||!pattern.test(path.basename(item.path))||item.name!==path.basename(item.path))return false;
  if(!fs.existsSync(item.path)||!fs.lstatSync(item.path).isDirectory()||fs.lstatSync(item.path).isSymbolicLink())return false;
  if(referenced.has(item.name)||newest.has(item.name)||processes.includes(item.path))return false;
  if(Date.now()-fs.statSync(item.path).mtimeMs<minimumAgeMs)return false;
  if(item.name.startsWith('pg-test-'))return fs.existsSync(path.join(item.path,'data/PG_VERSION'))&&
    fs.existsSync(path.join(item.path,'postgres.log'))&&!fs.existsSync(path.join(item.path,'data/postmaster.pid'));
  return fs.existsSync(path.join(item.path,'minio.log'))&&fs.existsSync(path.join(item.path,'data/.minio.sys'));
}
const processes=()=>execFileSync('ps',['-axo','command'],{encoding:'utf8',maxBuffer:8*1024**2});
if(process.argv[2]==='--apply'){
  const manifestPath=path.resolve(process.argv[3]??'');
  if(path.dirname(manifestPath)!==root||!path.basename(manifestPath).startsWith('cleanup-plan-'))throw Error('INVALID_PLAN_PATH');
  const plan=JSON.parse(fs.readFileSync(manifestPath,'utf8'));
  if(plan.workspace!==workspace||plan.root!==root||plan.status!=='inventory')throw Error('INVALID_PLAN');
  const live=processes();
  if(!plan.targets.every(item=>safe(item,live)))throw Error('TARGET_STATE_CHANGED');
  const removed=[];
  for(const item of plan.targets){
    // Each target is an explicit, validated immediate child, never the runtime/workspace root.
    fs.rmSync(item.path,{recursive:true,force:false});removed.push(item.path);
  }
  const result={status:'removed',removed,estimated_reclaimed_bytes:plan.estimated_bytes,
    retained:'all referenced evidence services, newest ten per type, active/recent services, source and benchmark outputs'};
  fs.writeFileSync(manifestPath.replace('.json','-result.json'),JSON.stringify(result,null,2),{flag:'wx',mode:0o600});
  console.log(JSON.stringify({status:result.status,count:removed.length,estimated_reclaimed_bytes:plan.estimated_bytes}));
}else{
  const live=processes(),targets=directories.filter(item=>safe(item,live));
  let estimated_bytes=0;
  if(targets.length){
    const sizes=execFileSync('du',['-sk',...targets.map(x=>x.path)],{encoding:'utf8',maxBuffer:8*1024**2});
    estimated_bytes=sizes.trim().split('\n').reduce((sum,line)=>sum+Number(line.split('\t')[0])*1024,0);
  }
  const manifest=path.join(root,`cleanup-plan-${Date.now()}.json`);
  fs.writeFileSync(manifest,JSON.stringify({workspace,root,status:'inventory',estimated_bytes,targets,
    referenced:[...referenced].sort(),newest:[...newest].sort()},null,2),{flag:'wx',mode:0o600});
  console.log(JSON.stringify({manifest,eligible:targets.length,estimated_bytes,all_service_directories:directories.length,
    protected_references:referenced.size,kept_latest:newest.size}));
}

// User-authorized synthetic test scratch cleanup. Never deletes published artifacts.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const workspace=fs.realpathSync(process.cwd());
if(workspace!=='/Users/jj/Desktop/ac_event_agent')throw Error('WRONG_WORKSPACE');
const runtime=path.join(workspace,'.runtime');
const names=new Set(['work.duckdb','scope.duckdb']);
const isSpill=file=>/^duckdb_temp_storage_(?:DEFAULT|S\d+K)-\d+\.tmp$/.test(path.basename(file))&&
  /^(?:work|scope)\.duckdb\.tmp$/.test(path.basename(path.dirname(file)));
const rootPattern=/^(?:cv05-(?:(?:100k|1m)-v2-\d+|(?:holdout-trigger-1m|validation-1m-window-cache|exploration-trigger-reuse-1m|exploration-trigger-global-1m|trigger-1m-diagnose|search-1m-optimized)-\d+)|benchmark-(?:10m|stress-1m|1m|100k|stress-100k)-001|local-workspace-flow-[a-f0-9]{8})$/;
const processes=()=>execFileSync('ps',['-axo','command'],{encoding:'utf8'});
function eligible(root,file,live){
 const receipt=[path.join(root,'result.json'),path.join(root,'product-acceptance.json'),path.join(root,'result','manifest.json'),path.join(root,'manifest.json')].find(p=>fs.existsSync(p));
 if(!receipt)return false;
 const result=JSON.parse(fs.readFileSync(receipt,'utf8'));
 const terminal=['passed','failed'].includes(result.status)||
   (path.basename(receipt)==='manifest.json'&&['validation','predicates','search'].includes(result.stage));
 if(!terminal||result.synthetic!==true||live.includes(root)||live.includes(path.relative(workspace,root)))return false;
 if(!file.startsWith(root+path.sep)||(!names.has(path.basename(file))&&!isSpill(file)))return false;
 if(fs.realpathSync(file)!==file||!fs.statSync(file).isFile())return false;
 // Spill files have no analysis value and can be recreated from retained input.
 // They are eligible only after the synthetic root is authoritatively terminal.
 if(isSpill(file))return true;
 // Only completed stage scratch; retain unfinished stage databases for diagnosis.
 const manifest=path.join(path.dirname(file),'manifest.json');
 if(!fs.existsSync(manifest))return false;
 const data=JSON.parse(fs.readFileSync(manifest,'utf8'));
 return !(data.artifacts??[]).some(item=>item.path===path.basename(file));
}
if(process.argv[2]==='--apply'){
 const manifest=path.resolve(process.argv[3]??'');
 if(path.dirname(manifest)!==runtime||!/^scratch-cleanup-\d+\.json$/.test(path.basename(manifest)))throw Error('INVALID_PLAN');
 const plan=JSON.parse(fs.readFileSync(manifest,'utf8')),live=processes();
 if(plan.workspace!==workspace||plan.status!=='inventory')throw Error('INVALID_PLAN');
 for(const item of plan.targets){
  if(path.dirname(item.root)!==runtime||!rootPattern.test(path.basename(item.root))||
    !eligible(item.root,item.file,live)||fs.statSync(item.file).size!==item.bytes||
    fs.statSync(item.file).mtimeMs!==item.mtime)throw Error('TARGET_STATE_CHANGED');
 }
 for(const item of plan.targets)fs.unlinkSync(item.file);
 const result={status:'removed',targets:plan.targets,reclaimed_bytes:plan.targets.reduce((s,x)=>s+x.bytes,0),
  retained:'all source, result.json, manifests, Parquet, reports, unfinished stages and active runs'};
 fs.writeFileSync(manifest.replace('.json','-result.json'),JSON.stringify(result,null,2),{flag:'wx',mode:0o600});
 console.log(JSON.stringify({status:result.status,count:plan.targets.length,reclaimed_bytes:result.reclaimed_bytes}));
}else{
 const targets=[],live=processes();
 function walk(root,dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
  const file=path.join(dir,entry.name);
  if(entry.isSymbolicLink())continue;
  if(entry.isDirectory())walk(root,file);
  else if((names.has(entry.name)||isSpill(file))&&eligible(root,file,live)){
   const stat=fs.statSync(file);targets.push({root,file,bytes:stat.size,mtime:stat.mtimeMs});
  }
 }}
 for(const entry of fs.readdirSync(runtime,{withFileTypes:true})){
  if(!entry.isDirectory()||!rootPattern.test(entry.name))continue;
  const root=path.join(runtime,entry.name);
  walk(root,root);
 }
 const manifest=path.join(runtime,`scratch-cleanup-${Date.now()}.json`);
 fs.writeFileSync(manifest,JSON.stringify({workspace,status:'inventory',targets},null,2),{flag:'wx',mode:0o600});
 console.log(JSON.stringify({manifest,count:targets.length,bytes:targets.reduce((s,x)=>s+x.bytes,0)}));
}

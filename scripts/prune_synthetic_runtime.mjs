// Run only with explicit user authorization. Never removes fixtures or live workspaces.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const root='/Users/jj/Desktop/ac_event_agent/.runtime';
const manifest='/Users/jj/Desktop/ac_event_agent/evidence/CV04-runtime-cleanup.json';
const mode=process.argv[2];
if(!['plan','execute'].includes(mode))throw Error('Use plan or execute');
const processes=execFileSync('ps',['-axo','pid=,command='],{encoding:'utf8'});
function validate(target){
  if(path.dirname(target)!==root||! /^(pg|s3)-test-[a-zA-Z0-9_]+$/.test(path.basename(target)))throw Error('Invalid target');
  if(fs.lstatSync(target).isSymbolicLink()||fs.realpathSync(target)!==target)throw Error('Symlink target');
  if(processes.includes(target))throw Error('Live process target: '+target);
  const marker=path.basename(target).startsWith('pg-')?'postgres.log':'minio.log';
  if(!fs.existsSync(path.join(target,marker)))throw Error('Missing synthetic marker');
  const pidFile=path.join(target,'data','postmaster.pid');
  if(fs.existsSync(pidFile)){
    const pid=Number(fs.readFileSync(pidFile,'utf8').split('\n')[0]);
    if(!Number.isInteger(pid)||pid<=0)throw Error('Invalid PID');
    try{process.kill(pid,0);throw Error('Live PID '+pid);}catch(error){if(error.code!=='ESRCH')throw error;}
  }
}
if(mode==='plan'){
  if(fs.existsSync(manifest))throw Error('Manifest already exists');
  const targets=[],skipped=[];
  for(const name of fs.readdirSync(root).sort()){
    if(!/^(pg|s3)-test-[a-zA-Z0-9_]+$/.test(name))continue;
    const target=path.join(root,name);
    try{validate(target);targets.push(target);}catch(error){skipped.push({target,reason:error.message});}
  }
  fs.writeFileSync(manifest,JSON.stringify({authorization:'User: 測試檔可以刪除',targets,skipped},null,2),{flag:'wx'});
  console.log(JSON.stringify({manifest,targets:targets.length,skipped:skipped.length}));
}else{
  const plan=JSON.parse(fs.readFileSync(manifest,'utf8'));
  for(const target of plan.targets)validate(target); // Validate every exact target before any deletion.
  for(const target of plan.targets)fs.rmSync(target,{recursive:true,force:false});
  console.log(JSON.stringify({removed:plan.targets.length,manifest,remainingTargets:plan.targets.filter(p=>fs.existsSync(p)).length}));
}

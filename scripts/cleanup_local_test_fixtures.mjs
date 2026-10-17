// Remove only stopped LocalPostgres/LocalS3 fixtures created after a supplied epoch.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';

const workspace=fs.realpathSync(process.cwd());
if(workspace!=='/Users/jj/Desktop/ac_event_agent')throw Error('WRONG_WORKSPACE');
const runtime=path.join(workspace,'.runtime');
const cutoff=Number(process.argv[2]);
if(!Number.isFinite(cutoff)||cutoff<=0)throw Error('INVALID_CUTOFF');
const keep=new Set(process.argv.slice(3));
const live=execFileSync('ps',['-Ao','command'],{encoding:'utf8'});
let count=0,reclaimed=0;
function bytes(directory){let result=0;for(const entry of fs.readdirSync(directory,{withFileTypes:true})){
 const file=path.join(directory,entry.name);if(entry.isSymbolicLink())continue;
 if(entry.isDirectory())result+=bytes(file);else result+=fs.statSync(file).size;
}return result;}
for(const entry of fs.readdirSync(runtime,{withFileTypes:true})){
 if(!entry.isDirectory()||keep.has(entry.name)||!/^(?:pg|s3)-test-[A-Za-z0-9_]+$/.test(entry.name))continue;
 const target=path.join(runtime,entry.name),stat=fs.statSync(target);
 if(stat.mtimeMs<cutoff||live.includes(target))continue;
 const size=bytes(target);fs.rmSync(target,{recursive:true});count+=1;reclaimed+=size;
}
console.log(JSON.stringify({status:'removed_stopped_local_test_fixtures',count,reclaimed_bytes:reclaimed,kept:[...keep]}));

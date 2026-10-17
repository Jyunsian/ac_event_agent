import type { Fingerprint } from './upload-client';

export function fingerprintFile(file: File, progress: (bytes:number,total:number)=>void, signal?: AbortSignal): Promise<Fingerprint> {
  return new Promise((resolve,reject)=>{
    const worker = new Worker(new URL('./file-hash.worker.ts',import.meta.url),{type:'module'});
    const close = () => {worker.terminate();signal?.removeEventListener('abort',abort);};
    const abort = () => {close();reject(new DOMException('已暫停','AbortError'));};
    if (signal?.aborted) {abort();return;}
    signal?.addEventListener('abort',abort,{once:true});
    worker.onerror = () => {close();reject(new Error('FILE_HASH_FAILED'));};
    worker.onmessage = event => {
      if (event.data.kind === 'progress') progress(event.data.bytes,event.data.total);
      else if (event.data.kind === 'complete') {close();resolve(event.data.fingerprint);}
      else {close();reject(new Error('FILE_READ_FAILED'));}
    };
    worker.postMessage(file);
  });
}

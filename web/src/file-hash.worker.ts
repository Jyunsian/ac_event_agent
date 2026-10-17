import { sha256 } from '@noble/hashes/sha2.js';

self.onmessage = async (event: MessageEvent<File>) => {
  try {
    const file = event.data, hash = sha256.create();
    const chunk = 4*1024*1024;
    for (let offset=0;offset<file.size;offset+=chunk) {
      hash.update(new Uint8Array(await file.slice(offset,offset+chunk).arrayBuffer()));
      self.postMessage({kind:'progress',bytes:Math.min(offset+chunk,file.size),total:file.size});
    }
    const digest = Array.from(hash.digest(), b=>b.toString(16).padStart(2,'0')).join('');
    self.postMessage({kind:'complete',fingerprint:{sha256:digest,size_bytes:file.size}});
  } catch {self.postMessage({kind:'error',code:'FILE_READ_FAILED'});}
};

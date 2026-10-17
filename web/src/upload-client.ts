import { sha256 } from '@noble/hashes/sha2.js';

export type Fingerprint = {size_bytes: number; sha256: string};
export type UploadRecord = {id: string; role: 'users' | 'events'; filename: string; format: 'csv' | 'parquet';
  expected_size: number; expected_sha256: string; status: string; part_size: number; part_count: number};
type Resume = {status: string; missing_parts: number[]; part_size: number;
  parts: {part_number: number; size_bytes: number}[]; url?: string};

export class APIError extends Error {
  constructor(public code: string, public status = 0, public fields: string[] = []) {super(code);}
}
export function requestIdentity(value: string) {return Array.from(sha256(new TextEncoder().encode(value)), b=>b.toString(16).padStart(2,'0')).join('');}
export async function api<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal, idempotencyKey?: string): Promise<T> {
  const serialized = body === undefined ? undefined : JSON.stringify(body);
  // Each edit is a new intent (A → B → A must save A again); selected resumable operations supply stable keys.
  const key = serialized === undefined ? undefined : idempotencyKey || crypto.randomUUID();
  let response: Response;
  try {response = await fetch(path,{method, body:serialized, signal, headers:serialized === undefined ? {} : {'Content-Type':'application/json','Idempotency-Key':key!}});}
  catch (error) {if (signal?.aborted) throw new DOMException('已暫停','AbortError'); throw new APIError('NETWORK_UNAVAILABLE');}
  let value;
  try { value = await response.json(); } catch { throw new APIError('INVALID_SERVER_RESPONSE',response.status); }
  if (!response.ok) throw new APIError(value.error_code || 'INVALID_REQUEST', response.status,
    Array.isArray(value.detail) ? value.detail.map((entry:{loc?: unknown[]; msg?: string}) => `${entry.loc?.join('.') || ''}: ${entry.msg || ''}`) : []);
  return value as T;
}

export async function transferFile({datasetId, file, role, fingerprint, record, progress, signal}: {
  datasetId: string; file: File; role: 'users' | 'events'; fingerprint: Fingerprint;
  record?: UploadRecord; progress: (confirmed: number, total: number) => void; signal?: AbortSignal;
}): Promise<string> {
  if (!file.size || file.size !== fingerprint.size_bytes || !/^[0-9a-f]{64}$/.test(fingerprint.sha256)) throw new APIError('INVALID_FILE_FINGERPRINT');
  const format = file.name.toLowerCase().endsWith('.csv') ? 'csv' : file.name.toLowerCase().endsWith('.parquet') ? 'parquet' : null;
  if (!format) throw new APIError('CSV_OR_PARQUET_REQUIRED');
  if (record && (record.role !== role || record.expected_size !== file.size || record.expected_sha256 !== fingerprint.sha256)) throw new APIError('FILE_FINGERPRINT_MISMATCH');
  const payload = {role, filename:file.name, format, ...fingerprint};
  const id = record?.id || (await api<{upload_id: string}>(`/api/datasets/${datasetId}/uploads`, 'POST',
    payload,signal,requestIdentity(datasetId+JSON.stringify(payload)))).upload_id;
  const state = await api<Resume>(`/api/uploads/${id}/resume`,'POST',fingerprint,signal);
  if (state.status === 'completed') {progress(file.size,file.size);return id;}
  let confirmed = state.parts.reduce((sum,part)=>sum+part.size_bytes,0);
  progress(confirmed,file.size);
  for (const part_number of state.missing_parts) {
    signal?.throwIfAborted();
    const signed = await api<Resume>(`/api/uploads/${id}/parts`,'POST',{...fingerprint,part_number},signal);
    if (!signed.url) throw new APIError('PART_URL_MISSING');
    const start = (part_number-1)*state.part_size;
    const part = file.slice(start, Math.min(file.size,start+state.part_size));
    let response: Response;
    try {response = await fetch(signed.url,{method:'PUT',body:part,signal});}
    catch {if (signal?.aborted) throw new DOMException('已暫停','AbortError');throw new APIError('STORAGE_TRANSFER_FAILED');}
    if (!response.ok) throw new APIError('STORAGE_TRANSFER_FAILED',response.status);
    confirmed += part.size; progress(confirmed,file.size);
  }
  await api(`/api/uploads/${id}/complete`,'POST',fingerprint,signal);
  return id;
}

import type {Candidate} from './report-model';

export type CandidateQuery={page?:number;window_hours?:number;family?:'atom'|'compound'|'sequence';
  ad_format?:string;evidence_status?:'historically_validated'|'historically_supported'|'not_supported'|'exploratory'|'insufficient_data';
  category?:'iaa'|'session_retention'|'level_progress'|'level_friction'|'cross_category'|'sequence';
  role?:'價值差較大'|'覆蓋較廣'|'達標較快'|'unselected';sort?:'candidate_id'|'difference_usd'|'coverage'|'p90_seconds';descending?:boolean};
export type CandidateSummary={event_spec:Candidate['event_spec'];family:string;ad_formats:string[];role:string|null;
  selection:Record<string,unknown>;timing_status:string;triggered_users:number|null;untriggered_users:number|null;
  triggered_arpu_usd:number|null;untriggered_arpu_usd:number|null;all_arpu_usd:number|null;difference_usd:number|null;
  coverage:number|null;median_seconds:number|null;p90_seconds:number|null};
export type CatalogEntry={candidate_id:string;window_hours:number;evidence_status:string;reasons:string[];detail_sha256:string;summary?:CandidateSummary};
export type CandidatePage={run_id:string;report_version:number;report_sha256:string;catalog_sha256:string;
  evaluated_count:number;comparison_users:number;filtered_count:number;page:number;page_size:50;priority_ids:string[];items:CatalogEntry[]};
export type CandidateScope={runId:string;version:number;reportSha:string;catalogSha:string};
export type CandidateDetail={schema_version:'2.0'|'3.0'|'4.0';run_id:string;dataset_id:string;candidate_id:string;frozen_sha256:string;
  event_spec:Candidate['event_spec'];validation:{candidate_id:string;metrics:Candidate['metrics'];evidence_status:string;reasons:string[];[key:string]:unknown};
  exploration:Record<string,unknown>;selection:Record<string,unknown>;source_diagnostics:Record<string,unknown>[]|null;
  revenue_decomposition:Record<string,unknown>|null;timing_status:string};
const digest=(value:unknown)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
function invalid():never{throw new Error('CANDIDATE_RESPONSE_INVALID');}
function object(value:unknown):asserts value is Record<string,any>{if(!value||typeof value!=='object'||Array.isArray(value))invalid();}
function strings(value:unknown):asserts value is string[]{if(!Array.isArray(value)||!value.every(v=>typeof v==='string'))invalid();}
export function decodeCandidatePage(value:unknown,scope:CandidateScope):CandidatePage{
  object(value);
  if(value.run_id!==scope.runId||value.report_version!==scope.version||value.report_sha256!==scope.reportSha||value.catalog_sha256!==scope.catalogSha)invalid();
  for(const key of ['evaluated_count','comparison_users','filtered_count','page'])if(!Number.isInteger(value[key]))invalid();
  if(value.evaluated_count<0||value.evaluated_count>2000||value.comparison_users<0||value.filtered_count<0||value.filtered_count>value.evaluated_count||value.page<1||value.page>40||value.page_size!==50)invalid();
  strings(value.priority_ids);
  if(value.priority_ids.length>10||new Set(value.priority_ids).size!==value.priority_ids.length||!value.priority_ids.every(digest))invalid();
  if(!Array.isArray(value.items)||value.items.length!==Math.min(50,Math.max(0,value.filtered_count-(value.page-1)*50)))invalid();
  const ids=new Set();
  for(const entry of value.items){
    object(entry);if(!digest(entry.candidate_id)||!digest(entry.detail_sha256)||ids.has(entry.candidate_id))invalid();ids.add(entry.candidate_id);
    if(typeof entry.window_hours!=='number'||!Number.isFinite(entry.window_hours)||entry.window_hours<=0||entry.window_hours>168)invalid();
    if(!['historically_validated','historically_supported','not_supported','exploratory','insufficient_data'].includes(entry.evidence_status))invalid();strings(entry.reasons);
    if(entry.summary!==undefined){
      const row=entry.summary;object(row);object(row.event_spec);object(row.event_spec.predicate);object(row.selection);
      if(row.event_spec.window_hours!==entry.window_hours||typeof row.event_spec.origin!=='string')invalid();
      if(!['atom','compound','sequence'].includes(row.family))invalid();strings(row.ad_formats);
      if(![null,'價值差較大','覆蓋較廣','達標較快'].includes(row.role)||!['observed','assumed_event_time'].includes(row.timing_status))invalid();
      for(const key of ['triggered_users','untriggered_users','triggered_arpu_usd','untriggered_arpu_usd','all_arpu_usd','difference_usd','coverage','median_seconds','p90_seconds']){
        const n=row[key];if(n!==null&&(typeof n!=='number'||!Number.isFinite(n)||(key!=='difference_usd'&&n<0)))invalid();
      }
      for(const key of ['triggered_users','untriggered_users'])if(row[key]!==null&&!Number.isInteger(row[key]))invalid();
      if(row.triggered_users!==null&&row.untriggered_users!==null&&row.triggered_users+row.untriggered_users>value.comparison_users)invalid();
      if(row.coverage!==null&&row.coverage>1)invalid();
    }
  }
  return value as CandidatePage;
}
export function candidateQueryString(query:CandidateQuery,includePage=true){
  const params=new URLSearchParams();
  for(const [key,value] of Object.entries(query))if(value!==undefined&&(includePage||key!=='page'))params.set(key,String(value));
  return params;
}
export function candidateExportUrl(scope:CandidateScope,format:'csv'|'json'|'html',query?:CandidateQuery){
  const params=candidateQueryString(query??{},false);params.set('scope',query?'filtered':'complete');
  return `/api/runs/${encodeURIComponent(scope.runId)}/reports/${scope.version}/candidate-exports/${format}?${params}`;
}
async function boundedJson(url:string,signal:AbortSignal){
  const response=await fetch(url,{signal});
  if(!response.ok)throw new Error(`CANDIDATE_READ_FAILED_${response.status}`);
  const reader=response.body?.getReader();if(!reader)invalid();
  const chunks:Uint8Array[]=[];let size=0;
  try{for(;;){const next=await reader.read();if(next.done)break;size+=next.value.length;if(size>1024*1024)invalid();chunks.push(next.value);}}
  catch(error){await reader.cancel();throw error;}finally{reader.releaseLock();}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
}
export async function fetchCandidatePage(scope:CandidateScope,query:CandidateQuery,signal:AbortSignal){
  const value=await boundedJson(`/api/runs/${encodeURIComponent(scope.runId)}/reports/${scope.version}/candidates?${candidateQueryString(query)}`,signal);
  const result=decodeCandidatePage(value,scope);
  if(result.page!==(query.page??1))invalid();return result;
}
export function decodeCandidateDetail(value:unknown,scope:CandidateScope,id:string,datasetId:string):CandidateDetail{
  object(value);
  if(value.run_id!==scope.runId||value.report_version!==scope.version||value.report_sha256!==scope.reportSha||
    value.catalog_sha256!==scope.catalogSha||!digest(value.sha256))invalid();
  const detail=value.content;object(detail);
  if(!['2.0','3.0','4.0'].includes(detail.schema_version)||detail.run_id!==scope.runId||detail.dataset_id!==datasetId||detail.candidate_id!==id||!digest(detail.frozen_sha256))invalid();
  object(detail.event_spec);object(detail.event_spec.predicate);object(detail.validation);object(detail.selection);object(detail.exploration);
  if(detail.validation.candidate_id!==id||!['historically_validated','historically_supported','not_supported','exploratory','insufficient_data'].includes(detail.validation.evidence_status))invalid();
  strings(detail.validation.reasons);
  if(detail.schema_version==='2.0'){
    if(detail.source_diagnostics!==null&&!Array.isArray(detail.source_diagnostics))invalid();
    if(detail.revenue_decomposition!==null)object(detail.revenue_decomposition);
  }else if(detail.schema_version==='4.0'){
    if(detail.analysis_version!=='4.0-time-aware'||!Array.isArray(detail.validation.observation)||detail.validation.observation.length!==6||!Array.isArray(detail.validation.holdout))invalid();
  }else if(!Array.isArray(detail.diagnostics)||detail.analysis_version!=='3.0-casual-game')invalid();
  if(!['observed','assumed_event_time'].includes(detail.timing_status))invalid();
  return detail as CandidateDetail;
}
export async function fetchCandidateDetail(scope:CandidateScope,id:string,datasetId:string,signal:AbortSignal){
  if(!digest(id))invalid();
  return decodeCandidateDetail(await boundedJson(`/api/runs/${encodeURIComponent(scope.runId)}/reports/${scope.version}/candidates/${id}`,signal),scope,id,datasetId);
}
export type CandidateSearch={summary:Record<string,any>;items:Record<string,any>[];page:number;page_size:number;pruning_count:number;sha256:string};
export type RevenuePoint={candidate_id:string;threshold_usd:number;coverage:number|null;difference_usd:number|null;sample_size:number|null;detail_sha256:string;evidence_status:string};
export type RevenueGroup={window_hours:number;ad_format:string;points:RevenuePoint[]};
export async function fetchRevenueGroups(scope:CandidateScope,signal:AbortSignal):Promise<RevenueGroup[]>{
  const value=await boundedJson(`/api/runs/${encodeURIComponent(scope.runId)}/reports/${scope.version}/candidate-revenue-series`,signal);
  object(value);
  if(value.run_id!==scope.runId||value.report_version!==scope.version||value.report_sha256!==scope.reportSha||value.catalog_sha256!==scope.catalogSha||!Array.isArray(value.groups))invalid();
  const ids=new Set(),groups=new Set();
  for(const g of value.groups){
    object(g);const key=JSON.stringify([g.window_hours,g.ad_format]);
    if(![1,3,6,12,24,48,72,96,120,144,168].includes(g.window_hours)||typeof g.ad_format!=='string'||groups.has(key)||!Array.isArray(g.points))invalid();groups.add(key);
    let previous=-Infinity;
    for(const p of g.points){
      object(p);if(!digest(p.candidate_id)||!digest(p.detail_sha256)||ids.has(p.candidate_id))invalid();ids.add(p.candidate_id);
      if(typeof p.threshold_usd!=='number'||!Number.isFinite(p.threshold_usd)||p.threshold_usd<=0||p.threshold_usd<previous)invalid();previous=p.threshold_usd;
      for(const k of ['coverage','difference_usd'])if(p[k]!==null&&(typeof p[k]!=='number'||!Number.isFinite(p[k])))invalid();
      if(p.coverage!==null&&(p.coverage<0||p.coverage>1))invalid();
      if(p.sample_size!==null&&(!Number.isSafeInteger(p.sample_size)||p.sample_size<0))invalid();
      if(!['historically_validated','historically_supported','not_supported','exploratory','insufficient_data'].includes(p.evidence_status))invalid();
    }
  }
  if(ids.size>2000)invalid();
  return value.groups;
}
export async function fetchCandidateSearch(scope:CandidateScope,page:number,signal:AbortSignal):Promise<CandidateSearch>{
  const value=await boundedJson(`/api/runs/${encodeURIComponent(scope.runId)}/reports/${scope.version}/candidate-search?page=${page}`,signal);
  object(value);object(value.summary);
  if(value.run_id!==scope.runId||value.report_version!==scope.version||value.report_sha256!==scope.reportSha||value.catalog_sha256!==scope.catalogSha||!digest(value.sha256)||
      value.page!==page||value.page_size!==50||!Number.isInteger(value.pruning_count)||value.pruning_count<0||!Array.isArray(value.items)||value.items.length>50)invalid();
  return value as CandidateSearch;
}

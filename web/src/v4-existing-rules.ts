export type ExistingRuleInput={name:string;metric:string;threshold:number;deadline:number};
const definition:Record<string,[string,string]>={ad_revenue_sum:['iaa','ad_impression'],ad_count:['iaa','ad_impression'],session_count:['session_retention','session_start'],level_complete_count:['level_progress','level_complete'],level_fail_count:['level_friction','level_fail']};
export async function existingRule(input:ExistingRuleInput){
  if(!definition[input.metric]||!input.name.trim()||!Number.isFinite(input.threshold)||input.threshold<=0||![24,48,72,96,120,144].includes(input.deadline))throw new Error('請填入有效的規則名稱、正數門檻和觀察期限。');
  const [category,event]=definition[input.metric];
  const rule:Record<string,unknown>={analysis_version:'4.0-time-aware',category,indicator_type:input.metric,mode:'cumulative',rolling_hours:null,
    predicate:{node:'atom',metric:input.metric,comparator:'gte',threshold:input.threshold,minimum_denominator:0,scope:category==='iaa'?{ad_format:'all'}:{}},dependencies:[event]};
  function canonical(v:any):any{return Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;}
  const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(canonical(rule))));
  rule.rule_id=[...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,'0')).join('');
  return {name:input.name.trim(),deadline_hours:input.deadline,rule};
}

export type ReferenceContext={selected_run_id:string;selected_candidate_id:null;report_version:number};
type EvidenceEvent={seq?:number;turn_id:string;kind:string;payload:{role?:string;context?:{selected_run_id:string;report_version:number};run_id?:string;report_version?:number;references?:{evidence_id:string;run_id:string;report_version?:number}[]}};
// Only receipts available before this message in the same conversation can bind.
// Old callers without a message sequence are restricted to their own turn.
export function referenceBinding(events:EvidenceEvent[],turnId:string,reference:string,messageSeq?:number):ReferenceContext|null{
  if(!/^report:[0-9a-f-]{36}#\//i.test(reference))return null;
  const matches:ReferenceContext[]=[];
  for(const event of events){
    if(event.kind!=='tool_completed')continue;
    if(messageSeq===undefined?event.turn_id!==turnId:(!Number.isSafeInteger(event.seq)||event.seq!>=messageSeq))continue;
    for(const ref of event.payload.references||[]){
      if(ref.evidence_id!==reference)continue;
      const pinned=events.find(item=>item.turn_id===event.turn_id&&item.kind==='message_created'&&item.payload.role==='user')?.payload.context;
      const version=ref.report_version??(event.payload.run_id===ref.run_id?event.payload.report_version:undefined)??(pinned?.selected_run_id===ref.run_id?pinned.report_version:undefined);
      if(!Number.isSafeInteger(version)||version!<1||!ref.run_id)continue;
      matches.push({selected_run_id:ref.run_id,selected_candidate_id:null,report_version:version!});
    }
  }
  if(!matches.length)return null;
  const first=matches[0];
  return matches.every(row=>row.selected_run_id===first.selected_run_id&&row.report_version===first.report_version)?first:null;
}

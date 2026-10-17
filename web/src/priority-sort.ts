import type {Candidate} from './report-model';

export function sortPriority(rows:Candidate[],sort:string,v2:boolean):Candidate[]{
  const copy=rows.slice();
  if(sort==='original')return copy;
  const metric=(row:Candidate):number|null=>{
    const comparison=row.metrics?.comparisons as Record<string,unknown>|undefined;
    const value=sort==='coverage'?row.metrics?.coverage:sort==='speed'?row.metrics?.delay_seconds.p90:
      v2?comparison?.triggered_minus_untriggered:row.metrics?.groups.triggered.arpu_usd;
    return typeof value==='number'&&Number.isFinite(value)?value:null;
  };
  return copy.sort((a,b)=>{
    const x=metric(a),y=metric(b),tie=a.candidate_id.localeCompare(b.candidate_id);
    return x===null?(y===null?tie:1):y===null?-1:(sort==='speed'?x-y:y-x)||tie;
  });
}

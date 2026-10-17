"""Qualification comes from fixed-rule validation, never an Agent-written outcome."""


def assess_recheck(recheck,validation,baseline_reasons):
    if recheck is None:return None
    validation=validation or {}
    policy=validation.get('validation_policy') or {}
    independent=policy.get('eligible') is True
    rows={row['candidate_id']:row for row in validation.get('results',[])}
    assessments=[]
    for source in recheck['sources']:
        row=rows.get(source['candidate_id'])
        reasons=sorted(set((row or {}).get('reasons',[])+policy.get('reasons',[])+baseline_reasons))
        if not row:status='not_evaluated'
        elif not independent:status='exploratory_only'
        elif row['evidence_status']=='historically_validated':status='reusable_evidence'
        elif (row['evidence_status']=='insufficient_data' or row.get('metrics') is None or
              any(reason in {'QUALITY_GATE_FAILED','FEATURE_CAPABILITY_DISABLED','UNKNOWN_REVENUE'} or
                  reason.startswith('INSUFFICIENT') for reason in reasons)):status='insufficient_evidence'
        else:status='not_supported'
        assessments.append({'finding_id':source['finding_id'],'candidate_id':source['candidate_id'],
                            'source_run_id':source['source_run_id'],'status':status,'reasons':reasons,
                            'independent_batch_eligible':independent,'reusable':status=='reusable_evidence'})
    return {**recheck,'assessments':assessments,
            'interpretation':'Reusable historical evidence is not campaign uplift; every subsequent batch still requires validation.'}

import pytest
from server.analysis.finding_assessment import assess_recheck


@pytest.mark.parametrize('eligible,evidence,metrics,expected',[
    (True,'historically_validated',{},'reusable_evidence'),
    (False,'historically_validated',{},'exploratory_only'),
    (True,'insufficient_data',{},'insufficient_evidence'),
    (True,'exploratory',{},'not_supported'),
    (True,'exploratory',None,'insufficient_evidence')])
def test_qualification_requires_independent_fixed_evidence(eligible,evidence,metrics,expected):
    source={'finding_id':'f','candidate_id':'c','source_run_id':'r'}
    result=assess_recheck({'sources':[source]}, {'validation_policy':{'eligible':eligible,'reasons':[]},
        'results':[{'candidate_id':'c','evidence_status':evidence,'metrics':metrics,'reasons':['test reason']}]},[])
    row=result['assessments'][0]
    assert row['status']==expected and row['reusable']==(expected=='reusable_evidence')
    assert row['reasons']==['test reason']
    assert assess_recheck({'sources':[source]},None,['quality blocked'])['assessments'][0]['status']=='not_evaluated'

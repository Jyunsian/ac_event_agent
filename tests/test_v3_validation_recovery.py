import copy

import pytest

from server.checkpoints import CheckpointError
from server.validation_batches import ValidationBatches


def test_v3_batch_contract_separates_cache_identity_and_forbids_partial_verdict():
    class Store:
        def lookup(self,*args):return None
    class Runner:
        identity={"pipeline_version":"v3","dataset_fingerprint":"d","config":{}}
        store=Store()
    batches=ValidationBatches(Runner(),"a"*64,["one","two"],version="3.0")
    assert batches._identity(0)[0]=="validation_batch_0000"
    payload={"schema_version":"3.0","stage":"validation_batch_0000","frozen_sha256":"a"*64,
             "family_correction_complete":False,"entries":[
                 {"row":{"candidate_id":name,"evidence_status":"pending_family_correction","metrics":None},
                  "test":{"testable":False,"p_value":1},"memberships":[[name,"app","user","unknown",None]]}
                 for name in ("one","two")]}
    assert batches._validate(payload,0)==payload["entries"]
    bad=copy.deepcopy(payload);bad["entries"][0]["row"]["evidence_status"]="historically_validated"
    with pytest.raises(CheckpointError,match="PARTIAL_VALIDATION_VERDICT_FORBIDDEN"):batches._validate(bad,0)
    assert ValidationBatches(Runner(),"a"*64,["one"],version="2.0")._identity(0)[2]!=ValidationBatches(Runner(),"a"*64,["one"],version="3.0")._identity(0)[2]

from server.analysis.casual_features import build_casual_features
from server.analysis.casual_freeze import freeze_casual_family
from server.analysis.casual_selection import select_casual_family
from server.analysis.casual_validation import validate_casual_family
from tests.test_v3_search import CONFIG,EXPORT,prepare_v3


def prepare_validation(root,batch_store=None,destination_name="validation"):
    prepare_v3(root)
    select_casual_family(root/"search",root/"selection")
    receipt=freeze_casual_family(root/"selection",root/"freeze")
    build_casual_features(root/"normalized",EXPORT,root/"full-features",CONFIG["windows_hours"])
    return validate_casual_family(root/"normalized",root/"full-features",root/"targets",root/"freeze",
                                  receipt["sha256"],root/destination_name,batch_store=batch_store)


def test_every_frozen_candidate_gets_full_family_holdout_result(tmp_path):
    output=prepare_validation(tmp_path/"data")
    assert output["family_correction_complete"] is True
    assert output["family_size"]==len(output["results"])>0
    assert all(row["inference"]["family_size"]==output["family_size"] for row in output["results"])
    assert all(row["inference"]["method"]=="holm" for row in output["results"])
    assert all(row["bootstrap"] is None or row["bootstrap"]["replicates"]==1000 for row in output["results"])
    for row in output["results"]:
        observed=row["observation"]["membership"]
        holdout=row["membership"]
        assert row["observation"]["scope"]=="all_mature_users"
        assert sum(observed[f"{status}_users"] for status in ("triggered","untriggered","unknown")) > sum(
            holdout[f"{status}_users"] for status in ("triggered","untriggered","unknown"))
        assert row["observation"]["interpretation"]=="descriptive_same_dataset_not_independent_validation"
    assert (tmp_path/"data/validation/holdout_membership.parquet").is_file()
    assert (tmp_path/"data/validation/diagnostics/diagnostics.json").is_file()


class MemoryBatches:
    size=2
    def __init__(self):self.data={}
    def load(self,index):return self.data.get(index)
    def save(self,index,entries):
        import copy
        self.data[index]=copy.deepcopy(entries)


def test_batch_resume_is_byte_identical_and_bad_identity_is_rejected(tmp_path):
    store=MemoryBatches();root=tmp_path/"data"
    first=prepare_validation(root,store,"validation-a")
    second=validate_casual_family(root/"normalized",root/"full-features",root/"targets",root/"freeze",
        first["frozen_sha256"],root/"validation-b",batch_store=store)
    assert (root/"validation-a/manifest.json").read_bytes()==(root/"validation-b/manifest.json").read_bytes()
    store.data[0][0]["row"]["candidate_id"]="bad"
    import pytest
    from server.analysis.ingest import IngestError
    with pytest.raises(IngestError,match="BATCH_ID_MISMATCH"):
        validate_casual_family(root/"normalized",root/"full-features",root/"targets",root/"freeze",
            first["frozen_sha256"],root/"validation-c",batch_store=store)
    assert not (root/"validation-c/manifest.json").exists()


def test_interruption_after_durable_batch_never_publishes_partial_family(tmp_path):
    class Interrupted(MemoryBatches):
        def save(self,index,entries):
            super().save(index,entries)
            raise RuntimeError("AFTER_DURABLE_BATCH")
    store=Interrupted();root=tmp_path/"data"
    prepare_v3(root);select_casual_family(root/"search",root/"selection")
    receipt=freeze_casual_family(root/"selection",root/"freeze")
    build_casual_features(root/"normalized",EXPORT,root/"full-features",CONFIG["windows_hours"])
    import pytest
    with pytest.raises(RuntimeError,match="AFTER_DURABLE_BATCH"):
        validate_casual_family(root/"normalized",root/"full-features",root/"targets",root/"freeze",
                               receipt["sha256"],root/"interrupted",batch_store=store)
    assert store.data and not (root/"interrupted/manifest.json").exists()

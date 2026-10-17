from server.analysis.casual_freeze import freeze_casual_family,load_casual_freeze
from server.analysis.casual_selection import select_casual_family
from server.pipeline import build_v3_discovery_stages
from tests.test_v3_search import CONFIG,EXPORT
from tests.test_v3_search import prepare_v3


def test_v3_freeze_is_immutable_and_holdout_independent(tmp_path):
    root=tmp_path/"data";prepare_v3(root);select_casual_family(root/"search",root/"selection")
    receipt=freeze_casual_family(root/"selection",root/"freeze")
    frozen=load_casual_freeze(root/"freeze",receipt["sha256"])
    assert frozen["family_size"]==len(frozen["candidate_ids"])
    assert frozen["rules"]["bootstrap_replicates"]==1000
    assert frozen["rules"]["min_group_users"]==2
    original=(root/"freeze/frozen.json").read_bytes()
    (root/"holdout-mutated.parquet").write_bytes(b"holdout mutation")
    freeze_casual_family(root/"selection",root/"freeze-copy")
    assert (root/"freeze-copy/frozen.json").read_bytes()==original


def test_pipeline_pre_holdout_boundary_runs_all_cg03_stages(tmp_path):
    root=tmp_path/"data";prepare_v3(root)
    result=build_v3_discovery_stages(root/"normalized",root/"targets",EXPORT,CONFIG,tmp_path/"pipeline")
    assert result["discovery_count"]>0 and result["family_size"]>0
    assert (tmp_path/"pipeline/freeze/frozen.json").is_file()

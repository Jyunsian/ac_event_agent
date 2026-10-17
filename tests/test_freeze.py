import json

import pytest

from server.analysis.freeze import freeze_candidates, load_frozen
from server.analysis.ingest import IngestError
from server.analysis.search import generate_candidates
from tests.test_search import CONFIG, prepare


def test_real_search_freeze_and_mutation_rejection(tmp_path):
    root = tmp_path/"data"
    prepare(root)
    search = generate_candidates(root/"exploration/features", root/"targets", CONFIG, root/"search")
    ids = [candidate["candidate_id"] for candidate in search["candidates"][:3]]
    receipt = freeze_candidates(root/"search", ids, root/"freeze")
    contract = load_frozen(root/"freeze", receipt["sha256"])
    assert [candidate["candidate_id"] for candidate in contract["candidates"]] == ids
    assert contract["rules"]["min_group_users"] == 100
    assert contract["rules"]["bootstrap_replicates"] == 1000
    assert "not_causal" in contract["rules"]["interpretation"]
    changed = json.loads(json.dumps(contract["candidates"]))
    changed[0]["window_hours"] = 168
    with pytest.raises(IngestError, match="FROZEN_CANDIDATES_MISMATCH"):
        load_frozen(root/"freeze", receipt["sha256"], candidates=changed)
    with pytest.raises(FileExistsError):
        freeze_candidates(root/"search", ids, root/"freeze")
    contract["rules"]["min_group_users"] = 2
    (root/"freeze/frozen.json").write_text(json.dumps(contract))
    with pytest.raises(IngestError, match="FROZEN_CONTRACT_CHANGED"):
        load_frozen(root/"freeze", receipt["sha256"])
    with pytest.raises(IngestError, match="FINALIST_NOT_IN_SEARCH"):
        freeze_candidates(root/"search", ["not-in-search"], root/"invalid")
    with pytest.raises(IngestError, match="INVALID_FINALIST_SELECTION"):
        freeze_candidates(root/"search", ids*2, root/"duplicates")

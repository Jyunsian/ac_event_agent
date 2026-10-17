import math

import pytest

from server.analysis.v3_contract import (
    ANALYSIS_VERSION,
    POLICY_IDENTITY,
    V3ContractError,
    candidate_identity,
    make_candidate,
    validate_artifact_identity,
    validate_candidate,
    validate_config,
)


def atom(metric="level_complete_count", threshold=2, minimum_denominator=0, comparator="gte"):
    return {"node": "atom", "metric": metric, "comparator": comparator,
            "threshold": threshold, "minimum_denominator": minimum_denominator, "scope": {}}


def candidate(**changes):
    fields = {
        "category": "level_progress",
        "indicator_type": "level_complete_count",
        "observation_start_hours": 0,
        "observation_end_hours": 24,
        "decision_time_hours": 24,
        "trigger_mode": "first_match_once",
        "predicate": atom(),
        "dependencies": ["level_complete"],
    }
    fields.update(changes)
    return make_candidate(**fields)


def test_identity_is_canonical_and_every_semantic_field_changes_it():
    value = candidate()
    assert value["analysis_version"] == ANALYSIS_VERSION
    assert value["candidate_id"] == candidate_identity(value)
    changed = candidate(observation_end_hours=48, decision_time_hours=48)
    assert changed["candidate_id"] != value["candidate_id"]
    reordered = {key: value[key] for key in reversed(value)}
    assert candidate_identity(reordered) == value["candidate_id"]
    assert len(POLICY_IDENTITY) == 64


def test_snapshot_direction_denominator_and_decision_are_enforced():
    valid = candidate(category="level_friction", indicator_type="complete_start_ratio",
                      trigger_mode="checkpoint_snapshot",
                      predicate=atom("complete_start_ratio", .75, 3, "lte"))
    assert validate_candidate(valid) is valid
    with pytest.raises(V3ContractError, match="TRIGGER_MODE_MISMATCH"):
        candidate(category="level_friction", indicator_type="complete_start_ratio",
                  predicate=atom("complete_start_ratio", .75, 3))
    with pytest.raises(V3ContractError, match="MINIMUM_DENOMINATOR_MISMATCH"):
        candidate(category="level_friction", indicator_type="complete_start_ratio",
                  trigger_mode="checkpoint_snapshot", predicate=atom("complete_start_ratio", .75, 0))
    with pytest.raises(V3ContractError, match="SNAPSHOT_DECISION"):
        candidate(category="level_friction", indicator_type="complete_start_ratio",
                  trigger_mode="checkpoint_snapshot", decision_time_hours=12,
                  predicate=atom("complete_start_ratio", .75, 3))


def test_sequence_template_constraints_and_long_gap_are_frozen():
    valid = candidate(category="sequence", indicator_type="level_fail_to_complete",
                      observation_end_hours=48, decision_time_hours=48,
                      predicate={"node":"sequence", "template":"level_fail_to_complete",
                                 "max_gap_seconds":86400, "repeats":1, "matching":"non_overlapping",
                                 "constraints":["same_level","different_attempt","strict_order"]},
                      dependencies=["level_fail", "level_complete"])
    assert validate_candidate(valid)
    broken = {**valid, "predicate": {**valid["predicate"], "constraints":["same_level","strict_order"]}}
    broken["candidate_id"] = candidate_identity(broken)
    with pytest.raises(V3ContractError, match="SEQUENCE_CONSTRAINT_MISMATCH"):
        validate_candidate(broken)


def test_cross_category_is_only_two_allowed_atoms_and_no_nonfinite_values():
    cross = candidate(category="cross_category", indicator_type="cross_category",
                      predicate={"node":"boolean", "operator":"and", "clauses":[
                          atom("level_complete_count", 2), atom("session_count", 2)]},
                      dependencies=["level_complete", "session_start"])
    assert validate_candidate(cross)
    with pytest.raises((V3ContractError, ValueError)):
        candidate(predicate=atom(threshold=math.nan))


def test_artifact_identity_requires_v3_and_all_hashes():
    identity = {
        "schema_version":"3.0", "analysis_version":ANALYSIS_VERSION,
        "run_id":"00000000-0000-4000-8000-000000000001",
        "dataset_id":"00000000-0000-4000-8000-000000000002",
        "pipeline_identity":"a"*64, "feature_identity":"b"*64, "policy_identity":"c"*64,
        "upstream_sha256":{"normalized":"d"*64},
    }
    assert validate_artifact_identity(identity) == identity
    with pytest.raises(V3ContractError):
        validate_artifact_identity({**identity, "analysis_version":"2.0"})


def test_identity_mismatch_is_rejected():
    value = candidate()
    value["candidate_id"] = "f" * 64
    with pytest.raises(V3ContractError, match="CANDIDATE_IDENTITY_MISMATCH"):
        validate_candidate(value)


def test_v3_config_has_explicit_limits():
    import json
    from pathlib import Path
    value = json.loads(Path("contracts/defaults.json").read_text())
    assert validate_config(value) == value
    with pytest.raises(V3ContractError, match="INVALID_V3_CONFIG"):
        validate_config({**value, "bootstrap_replicates": 100})

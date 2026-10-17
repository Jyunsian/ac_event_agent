"""Candidate Event V3 contracts and deterministic identities.

JSON Schema owns shape.  This module owns cross-field semantics that JSON Schema
cannot express and is deliberately free of data-dependent policy decisions.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSION = "3.0"
ANALYSIS_VERSION = "3.0-casual-game"
DISCOVERY_LIMIT = 20_000
VALIDATION_LIMIT = 2_000
MAX_PRIORITY = 10
BOOTSTRAP_REPLICATES = 1_000
CHECKPOINT_HOURS = 72

WINDOWS = {
    "iaa": (1, 3, 6, 12, 24, 48, 72, 96, 120, 144),
    "session_count": (3, 6, 12, 24, 48, 72, 96, 144),
    "retention": ((24, 48), (48, 72), (72, 96)),
    "level_progress": (1, 3, 6, 12, 24, 48, 72, 96, 120, 144),
    "level_friction": (6, 12, 24, 48, 72),
    "sequence": (1, 3, 6, 12, 24, 48),
}

CATEGORY_BUDGETS = {
    "iaa": (3_500, 350),
    "session_retention": (3_000, 300),
    "level_progress": (4_500, 450),
    "level_friction": (3_000, 300),
    "cross_category": (4_000, 400),
    "sequence": (2_000, 200),
}

METRIC_CATEGORIES = {
    "ad_count": "iaa", "ad_revenue_sum": "iaa",
    "session_count": "session_retention", "first_return_delay_seconds": "session_retention",
    "return_in_interval": "session_retention",
    "return_interval_count": "session_retention", "consecutive_return_days": "session_retention",
    "post_return_session_count": "session_retention", "post_return_engaged_seconds": "session_retention",
    "level_start_count": "level_progress", "level_complete_count": "level_progress",
    "distinct_completed_levels": "level_progress", "max_completed_level_index": "level_progress",
    "completed_level": "level_progress", "reached_level": "level_progress",
    "level_time_to_reach_seconds": "level_progress", "completes_per_session": "level_progress",
    "level_fail_count": "level_friction", "retry_same_level": "level_friction",
    "complete_after_fail": "level_friction", "session_after_fail": "level_friction",
    "attempts_per_level": "level_friction", "complete_start_ratio": "level_friction",
    "fail_start_ratio": "level_friction", "completion_duration_seconds": "level_friction",
    "consecutive_failures": "level_friction",
}

SNAPSHOT_METRICS = {
    "attempts_per_level", "complete_start_ratio", "fail_start_ratio",
    "completion_duration_seconds", "completes_per_session", "first_return_delay_seconds",
    "level_time_to_reach_seconds",
}

MINIMUM_DENOMINATORS = {
    "complete_start_ratio": 3,
    "fail_start_ratio": 3,
    "attempts_per_level": 2,
    "completion_duration_seconds": 2,
    "completes_per_session": 2,
}

SEQUENCE_RULES = {
    "level_start_to_complete": ("same_level", "same_attempt", "strict_order"),
    "level_fail_to_start": ("same_level", "different_attempt", "strict_order"),
    "level_fail_to_complete": ("same_level", "different_attempt", "strict_order"),
    "level_fail_to_session_end": ("same_session", "strict_order"),
    "session_start_to_level_complete": ("same_session", "strict_order"),
    "level_complete_to_ad_impression": ("same_session", "strict_order"),
    "rewarded_ad_to_level_complete": ("same_session", "strict_order"),
}

ALLOWED_CROSS_CATEGORY_PAIRS = {
    frozenset(("level_progress", "session_retention")),
    frozenset(("level_progress", "iaa")),
    frozenset(("level_friction", "session_retention")),
    frozenset(("session_retention", "iaa")),
}

_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "casual_game_v3.schema.json").read_text())
_VALIDATORS = {
    name: Draft202012Validator({**_SCHEMA, "$ref": f"#/$defs/{name}"}, format_checker=FormatChecker())
    for name in ("config", "candidate", "artifact_identity")
}


class V3ContractError(ValueError):
    pass


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def candidate_identity(candidate: dict) -> str:
    return digest({key: value for key, value in candidate.items() if key != "candidate_id"})


def _finite_tree(value) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            _finite_tree(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise V3ContractError("NONFINITE_VALUE")


def validate_candidate(candidate: dict, *, verify_identity: bool = True) -> dict:
    errors = sorted(_VALIDATORS["candidate"].iter_errors(candidate), key=lambda e: list(e.path))
    if errors:
        raise V3ContractError("INVALID_V3_CANDIDATE:" + errors[0].message)
    _finite_tree(candidate)
    start, end, decision = (candidate[key] for key in (
        "observation_start_hours", "observation_end_hours", "decision_time_hours"))
    if not start < end or not start <= decision <= end:
        raise V3ContractError("INVALID_OBSERVATION_INTERVAL")
    predicate = candidate["predicate"]
    node = predicate["node"]
    mode = candidate["trigger_mode"]
    if node == "atom":
        metric = predicate["metric"]
        if candidate["category"] != METRIC_CATEGORIES[metric]:
            raise V3ContractError("METRIC_CATEGORY_MISMATCH")
        if candidate["indicator_type"] != metric:
            raise V3ContractError("INDICATOR_METRIC_MISMATCH")
        expected_mode = "checkpoint_snapshot" if metric in SNAPSHOT_METRICS else "first_match_once"
        if mode != expected_mode:
            raise V3ContractError("TRIGGER_MODE_MISMATCH")
        if mode == "checkpoint_snapshot" and decision != end:
            raise V3ContractError("SNAPSHOT_DECISION_MUST_EQUAL_END")
        if predicate["comparator"] == "lte" and mode != "checkpoint_snapshot":
            raise V3ContractError("LTE_REQUIRES_SNAPSHOT")
        minimum = MINIMUM_DENOMINATORS.get(metric, 0)
        if predicate["minimum_denominator"] != minimum:
            raise V3ContractError("MINIMUM_DENOMINATOR_MISMATCH")
        if metric in ("complete_start_ratio", "fail_start_ratio") and not 0 <= predicate["threshold"] <= 1:
            raise V3ContractError("RATIO_THRESHOLD_OUT_OF_RANGE")
    elif node == "boolean":
        if (candidate["category"] != "cross_category" or candidate["indicator_type"] != "cross_category"
                or mode not in ("first_match_once", "checkpoint_snapshot")):
            raise V3ContractError("INVALID_CROSS_CATEGORY_HEADER")
        categories = frozenset(METRIC_CATEGORIES[clause["metric"]] for clause in predicate["clauses"])
        if len(categories) != 2 or categories not in ALLOWED_CROSS_CATEGORY_PAIRS:
            raise V3ContractError("CROSS_CATEGORY_PAIR_NOT_ALLOWED")
        if any(clause["comparator"] == "lte" or clause["metric"] in SNAPSHOT_METRICS for clause in predicate["clauses"]):
            if mode != "checkpoint_snapshot" or decision != end:
                raise V3ContractError("CROSS_SNAPSHOT_REQUIRED")
        elif mode != "first_match_once":
            raise V3ContractError("CROSS_FIRST_MATCH_REQUIRED")
    else:
        if candidate["category"] != "sequence" or mode != "first_match_once":
            raise V3ContractError("INVALID_SEQUENCE_HEADER")
        template = predicate["template"]
        if candidate["indicator_type"] != template:
            raise V3ContractError("INDICATOR_SEQUENCE_MISMATCH")
        if tuple(predicate["constraints"]) != SEQUENCE_RULES[template]:
            raise V3ContractError("SEQUENCE_CONSTRAINT_MISMATCH")
        if predicate["max_gap_seconds"] == 86400 and template != "level_fail_to_complete":
            raise V3ContractError("LONG_GAP_TEMPLATE_NOT_ALLOWED")
    if verify_identity and candidate["candidate_id"] != candidate_identity(candidate):
        raise V3ContractError("CANDIDATE_IDENTITY_MISMATCH")
    return candidate


def make_candidate(**fields) -> dict:
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "candidate_id": "0" * 64,
        **fields,
    }
    candidate["candidate_id"] = candidate_identity(candidate)
    return validate_candidate(candidate)


def validate_artifact_identity(value: dict) -> dict:
    errors = sorted(_VALIDATORS["artifact_identity"].iter_errors(value), key=lambda e: list(e.path))
    if errors:
        raise V3ContractError("INVALID_V3_ARTIFACT_IDENTITY:" + errors[0].message)
    return value


def validate_config(value: dict) -> dict:
    errors = sorted(_VALIDATORS["config"].iter_errors(value), key=lambda e: list(e.path))
    if errors:
        raise V3ContractError("INVALID_V3_CONFIG:" + errors[0].message)
    _finite_tree(value)
    return value


POLICY_IDENTITY = digest({
    "analysis_version": ANALYSIS_VERSION,
    "windows": WINDOWS,
    "category_budgets": CATEGORY_BUDGETS,
    "minimum_denominators": MINIMUM_DENOMINATORS,
    "sequence_rules": SEQUENCE_RULES,
    "allowed_cross_category_pairs": sorted(sorted(pair) for pair in ALLOWED_CROSS_CATEGORY_PAIRS),
    "limits": {"discovery": DISCOVERY_LIMIT, "validation": VALIDATION_LIMIT, "priority": MAX_PRIORITY},
    "discovery_policy":{"near_duplicate_jaccard":.995,"near_duplicate_coverage_delta":.005,
        "max_parents_per_category_window":20,"cross_parent_coverage_range":[.3,.7],
        "cross_parent_selection":"greedy_global_distinct_valid_membership_then_pareto","cross_parent_refinement_rounds":3},
})

"""Deterministic, non-overlapping two-step Casual Game sequence matching."""
from __future__ import annotations

from collections.abc import Iterable

from server.analysis.v3_contract import SEQUENCE_RULES


def strictly_after(first: dict, second: dict) -> bool:
    if second["event_time"] > first["event_time"]:
        return True
    if second["event_time"] < first["event_time"]:
        return False
    left, right = first.get("source_sequence"), second.get("source_sequence")
    return left is not None and right is not None and right > left


def _is_first(event: dict, template: str) -> bool:
    name = event["event_name"]
    return {
        "level_start_to_complete": name == "level_start",
        "level_fail_to_start": name == "level_fail",
        "level_fail_to_complete": name == "level_fail",
        "level_fail_to_session_end": name == "level_fail",
        "session_start_to_level_complete": name == "session_start",
        "level_complete_to_ad_impression": name == "level_complete",
        "rewarded_ad_to_level_complete": name == "ad_impression" and event.get("ad_format") == "rewarded",
    }[template]


def _is_second(event: dict, template: str) -> bool:
    return event["event_name"] == {
        "level_start_to_complete": "level_complete",
        "level_fail_to_start": "level_start",
        "level_fail_to_complete": "level_complete",
        "level_fail_to_session_end": "session_end",
        "session_start_to_level_complete": "level_complete",
        "level_complete_to_ad_impression": "ad_impression",
        "rewarded_ad_to_level_complete": "level_complete",
    }[template]


def _constraints_match(first: dict, second: dict, template: str) -> bool:
    constraints = SEQUENCE_RULES[template]
    if "same_level" in constraints and (not first.get("level_id") or first.get("level_id") != second.get("level_id")):
        return False
    if "same_attempt" in constraints and (not first.get("attempt_id") or first.get("attempt_id") != second.get("attempt_id")):
        return False
    if "different_attempt" in constraints and (not first.get("attempt_id") or not second.get("attempt_id")
                                                    or first.get("attempt_id") == second.get("attempt_id")):
        return False
    if "same_session" in constraints and (not first.get("session_id") or first.get("session_id") != second.get("session_id")):
        return False
    return True


def match_sequence(events: Iterable[dict], template: str, max_gap_seconds: int) -> list[dict]:
    if template not in SEQUENCE_RULES:
        raise ValueError("UNKNOWN_SEQUENCE_TEMPLATE")
    if max_gap_seconds not in (300, 1800, 7200, 86400):
        raise ValueError("INVALID_SEQUENCE_GAP")
    if max_gap_seconds == 86400 and template != "level_fail_to_complete":
        raise ValueError("LONG_GAP_TEMPLATE_NOT_ALLOWED")
    ordered = sorted(events, key=lambda e: (e["event_time"],
        e.get("source_sequence") is None, e.get("source_sequence") or 0, e["event_id"]))
    used: set[str] = set()
    matches = []
    for first in ordered:
        if first["event_id"] in used or not _is_first(first, template):
            continue
        for second in ordered:
            if second["event_id"] in used or second["event_id"] == first["event_id"] or not _is_second(second, template):
                continue
            if not strictly_after(first, second):
                continue
            gap = (second["event_time"] - first["event_time"]).total_seconds()
            if gap > max_gap_seconds:
                break
            if not _constraints_match(first, second, template):
                continue
            used.update((first["event_id"], second["event_id"]))
            matches.append({"template":template, "max_gap_seconds":max_gap_seconds,
                            "first_event_id":first["event_id"], "second_event_id":second["event_id"],
                            "matched_at":second["event_time"], "gap_seconds":gap})
            break
    return matches

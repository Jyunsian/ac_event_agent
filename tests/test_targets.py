import json

import duckdb
import pytest

from server.analysis.ingest import canonicalize
from server.analysis.targets import build_targets
from tests.test_ingest import HAND, MAPPING, sources, write_source
from tests.test_quality import EXPORT


def read_rows(path):
    with duckdb.connect() as c:
        result = c.execute("SELECT * FROM read_parquet(?) ORDER BY user_id", [str(path)])
        columns = [column[0] for column in result.description]
        return {row[1]: dict(zip(columns, row)) for row in result.fetchall()}


def test_hand_d7_boundary_maturity_and_zero_user(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    manifest = build_targets(tmp_path/"normalized", EXPORT, tmp_path/"targets")
    rows = read_rows(tmp_path/"targets/targets.parquet")
    expected = json.loads((HAND/"expected.json").read_text())
    for user, revenue in expected["d7_revenue_usd"].items():
        if revenue is None:
            assert rows[user]["d7_revenue_usd"] is None
            assert rows[user]["split"] == "excluded_immature"
        else:
            assert rows[user]["d7_revenue_usd"] == pytest.approx(revenue)
    assert manifest["mature_users"] == 5 and manifest["immature_users"] == 1
    assert sum(row["d7_revenue_usd"] or 0 for row in rows.values())/5 == pytest.approx(.064)
    assert manifest["split_definition"]["holdout_start_day"] == "2026-01-04"
    assert manifest["summary"]["exploration"]["users"] == 3
    assert manifest["summary"]["exploration"]["arpu_usd"] == pytest.approx(.2/3)


def test_holdout_revenue_cannot_change_split_or_exploration_targets(tmp_path):
    users = json.loads((HAND/"users.json").read_text())
    events = json.loads((HAND/"events.json").read_text())
    results = []
    for i in range(2):
        root = tmp_path/str(i)
        root.mkdir()
        adjusted = [{**event, "revenue_usd": 999} if i and event["user_id"] in ("u4", "u5")
                    and event["event_name"] == "ad_impression" else event for event in events]
        canonicalize([write_source(root, "users", users), write_source(root, "events", adjusted)], MAPPING, root/"normalized")
        manifest = build_targets(root/"normalized", EXPORT, root/"targets")
        rows = read_rows(root/"targets/targets.parquet")
        results.append((manifest, {key: row for key, row in rows.items() if row["split"] == "exploration"}))
    assert results[0][0]["split_id"] == results[1][0]["split_id"]
    assert results[0][1] == results[1][1]
    assert results[0][0]["summary"]["holdout"] != results[1][0]["summary"]["holdout"]


def test_insufficient_batches_and_exact_maturity(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    manifest = build_targets(tmp_path/"normalized", {**EXPORT, "complete_through": "2026-01-09T00:00:00Z"}, tmp_path/"targets")
    rows = read_rows(tmp_path/"targets/targets.parquet")
    assert manifest["mature_users"] == 2
    assert rows["u2"]["is_mature"] and rows["u2"]["d7_revenue_usd"] == 0
    assert manifest["split_status"] == "exploratory_only"
    assert manifest["summary"]["holdout"]["users"] == 0
    assert manifest["summary"]["holdout"]["arpu_usd"] is None


def test_missing_revenue_not_silently_removed_from_denominator(tmp_path):
    edge = json.loads((HAND/"edge_cases.json").read_text())[0]["event"]
    canonicalize(sources(tmp_path, extras=[edge]), MAPPING, tmp_path/"normalized")
    manifest = build_targets(tmp_path/"normalized", EXPORT, tmp_path/"targets")
    rows = read_rows(tmp_path/"targets/targets.parquet")
    assert rows["u1"]["d7_revenue_usd"] is None
    assert manifest["summary"]["exploration"] == {"users": 3, "unknown_targets": 1, "revenue_usd": None, "arpu_usd": None}


def test_whole_utc_day_batches_and_unique_user_assignment(tmp_path):
    users = json.loads((HAND/"users.json").read_text())
    events = json.loads((HAND/"events.json").read_text())
    # Same UTC day as u3 despite a non-midnight installation and source offset.
    users += [{**users[2], "user_id": f"same-day-{i}", "installed_at": "2026-01-03T23:59:59+00:00"} for i in range(20)]
    canonicalize([write_source(tmp_path, "users", users), write_source(tmp_path, "events", events)], MAPPING, tmp_path/"normalized")
    result = build_targets(tmp_path/"normalized", EXPORT, tmp_path/"targets")
    rows = read_rows(tmp_path/"targets/cohorts.parquet")
    assert len(rows) == 26
    assignments = {}
    for row in rows.values():
        if row["is_mature"]:
            assignments.setdefault(row["install_day"], set()).add(row["split"])
    assert all(len(groups) == 1 for groups in assignments.values())
    assert result["summary"]["exploration"]["users"] == 23
    assert result["summary"]["holdout"]["users"] == 2


def test_no_mature_users_has_no_zero_arpu_and_reproducible_output(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    export = {**EXPORT, "complete_through": "2026-01-01T00:00:00Z"}
    first = build_targets(tmp_path/"normalized", export, tmp_path/"first")
    second = build_targets(tmp_path/"normalized", export, tmp_path/"second")
    assert first == second
    assert first["mature_users"] == 0
    assert first["immature_users"] == 6
    assert first["summary"]["exploration"]["arpu_usd"] is None
    assert all(row["d7_revenue_usd"] is None for row in read_rows(tmp_path/"first/targets.parquet").values())
    with pytest.raises(FileExistsError):
        build_targets(tmp_path/"normalized", export, tmp_path/"first")

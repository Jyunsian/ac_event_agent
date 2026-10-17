import json
from pathlib import Path

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

from server.analysis.ingest import EVENT_TYPES, USER_TYPES, canonicalize
from tests.test_ingest import write_source

FIXTURE = Path("tests/fixtures/casual_v3")
MAPPING = {"users": {name:name for name in USER_TYPES}, "events": {name:name for name in EVENT_TYPES}}


def test_casual_fixture_is_schema_valid_and_expected_is_independent():
    schema = json.loads(Path("contracts/schema.json").read_text())
    users = json.loads((FIXTURE/"users.json").read_text())
    events = json.loads((FIXTURE/"events.json").read_text())
    expected = json.loads((FIXTURE/"expected.json").read_text())
    for definition, rows in (("user", users), ("event", events)):
        validator = Draft202012Validator({**schema, "$ref": f"#/$defs/{definition}"},
                                         format_checker=FormatChecker())
        for row in rows:
            validator.validate(row)
    assert expected["derivation"].startswith("Manually enumerated")
    assert len(users) == expected["input_users"] == 4
    assert len(events) == expected["input_events"] == 15
    assert expected["return_intervals"]["u1"]["[24,48)"] == "2026-01-02T00:00:00Z"
    assert expected["return_intervals"]["u1"]["[48,72)"] == "2026-01-03T00:00:00Z"
    assert expected["return_intervals"]["u1"]["[72,96)"] == "2026-01-04T00:00:00Z"
    assert expected["same_time_pair_without_source_sequence"] is False


def test_casual_fields_are_preserved_without_changing_sources(tmp_path):
    users = json.loads((FIXTURE/"users.json").read_text())
    events = json.loads((FIXTURE/"events.json").read_text())
    sources = [write_source(tmp_path, "users", users), write_source(tmp_path, "events", events)]
    original = [entry["sha256"] for entry in sources]
    manifest = canonicalize(sources, MAPPING, tmp_path/"normalized")
    assert manifest["ingest_version"] == "2.0-casual-game"
    assert manifest["counts"]["users"]["retained_rows"] == 4
    assert manifest["counts"]["events"]["retained_rows"] == 15
    assert [entry["sha256"] for entry in sources] == original
    with duckdb.connect() as connection:
        row = connection.execute("""SELECT level_id,level_index,attempt_id,level_mode,difficulty,
            revive_used,booster_used,app_version FROM read_parquet(?) WHERE event_id='u1-l1-a1-fail'""",
            [str(tmp_path/"normalized/events.parquet")]).fetchone()
    assert row == ("L1", 1, "a1", "main", "easy", False, True, "1.0.0")


def test_missing_level_index_is_retained_for_count_only_analysis(tmp_path):
    users = json.loads((FIXTURE/"users.json").read_text())[:1]
    event = {**json.loads((FIXTURE/"events.json").read_text())[1],
             "event_id":"missing-index", "level_index":None}
    manifest = canonicalize([write_source(tmp_path,"users",users),write_source(tmp_path,"events",[event])],
                            MAPPING,tmp_path/"normalized")
    assert manifest["counts"]["events"]["retained_rows"] == 1


def test_invalid_level_index_and_boolean_are_quarantined(tmp_path):
    users = json.loads((FIXTURE/"users.json").read_text())[:1]
    base = json.loads((FIXTURE/"events.json").read_text())[1]
    events = [{**base,"event_id":"negative-index","level_index":-1},
              {**base,"event_id":"bad-bool","revive_used":"not-a-bool"}]
    manifest = canonicalize([write_source(tmp_path,"users",users),write_source(tmp_path,"events",events)],
                            MAPPING,tmp_path/"normalized")
    reasons = manifest["counts"]["events"]["reasons"]
    assert reasons["invalid_level_index"] == 1
    assert reasons["invalid_revive_used"] == 1
    assert manifest["counts"]["events"]["retained_rows"] == 0

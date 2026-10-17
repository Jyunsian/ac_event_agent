import csv
import json
from pathlib import Path

import duckdb
import pytest

from server.analysis.ingest import EVENT_TYPES, USER_TYPES, IngestError, canonicalize, file_hash, ident

HAND = Path("tests/fixtures/hand")
MAPPING = {"users": {name: name for name in USER_TYPES}, "events": {name: name for name in EVENT_TYPES}}


def write_source(directory, role, rows, suffix="", parquet=False):
    types = USER_TYPES if role == "users" else EVENT_TYPES
    path = directory/f"{role}{suffix}.csv"
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(types))
        writer.writeheader()
        writer.writerows(rows)
    if parquet:
        new_path = path.with_suffix(".parquet")
        with duckdb.connect() as connection:
            connection.execute("SET TimeZone='UTC'")
            fields = ','.join(f'CAST({ident(name)} AS {dtype}) AS {ident(name)}' for name,dtype in types.items())
            connection.execute(f"COPY (SELECT {fields} FROM read_csv($1,all_varchar=true)) TO $2 (FORMAT PARQUET)", [str(path), str(new_path)])
        path = new_path
    return {"role": role, "path": str(path), "format": "parquet" if parquet else "csv", "sha256": file_hash(path)}


def sources(directory, parquet=False, extras=None):
    users = json.loads((HAND/"users.json").read_text())
    events = json.loads((HAND/"events.json").read_text()) + (extras or [])
    return [write_source(directory, "users", users, parquet=parquet),
            write_source(directory, "events", events[:9], "a", parquet),
            write_source(directory, "events", events[9:], "b", parquet)]


def rows(path, order):
    with duckdb.connect() as c:
        return c.execute(f"SELECT * FROM read_parquet(?) ORDER BY {order}", [str(path)]).fetchall()


def test_equivalent_csv_parquet_cross_file_dedup_and_sources_unchanged(tmp_path):
    left, right = tmp_path/"csv", tmp_path/"parquet"
    left.mkdir()
    right.mkdir()
    csv_sources, pq_sources = sources(left), sources(right, True)
    csv_result = canonicalize(csv_sources, MAPPING, left/"result")
    pq_result = canonicalize(pq_sources, MAPPING, right/"result")
    assert csv_result["counts"] == pq_result["counts"]
    assert csv_result["counts"]["users"]["retained_rows"] == 6
    assert csv_result["counts"]["events"]["input_rows"] == 17
    assert csv_result["counts"]["events"]["duplicate_rows"] == 1
    assert csv_result["counts"]["events"]["retained_rows"] == 16
    for role, order in (("users", "app_id,user_id"), ("events", "app_id,event_id")):
        assert rows(left/f"result/{role}.parquet", order) == rows(right/f"result/{role}.parquet", order)
    for source in csv_sources+pq_sources:
        assert file_hash(source["path"]) == source["sha256"]
    assert (left/"result/manifest.json").exists()
    with pytest.raises(FileExistsError):
        canonicalize(csv_sources, MAPPING, left/"result")


def test_conflicts_bad_time_and_orphans_are_audited(tmp_path):
    edges = json.loads((HAND/"edge_cases.json").read_text())
    extras = [item["event"] for item in edges]
    extras += [{**extras[0], "event_id": "naive", "event_time": "2026-01-01"},
               {**extras[0], "event_id": "bad-date", "event_time": "2026-99-01T00:00:00Z"}]
    result = canonicalize(sources(tmp_path, extras=extras), MAPPING, tmp_path/"result")
    counts = result["counts"]["events"]
    assert counts["reasons"]["invalid_event_time"] == 2
    assert counts["link_rejections"] == {"unmatched_user": 1, "before_install": 1}
    assert counts["quarantined_keys"] == 3  # conflict u1-a1 and two invalid-time IDs
    with duckdb.connect() as c:
        assert c.execute("SELECT count(*) FROM read_parquet(?) WHERE event_id='u1-a1'", [str(tmp_path/"result/events.parquet")]).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM read_parquet(?) WHERE event_id='u1-a1'", [str(tmp_path/"result/conflicting_events_rows.parquet")]).fetchone()[0] == 3
        assert c.execute("SELECT revenue_usd FROM read_parquet(?) WHERE event_id='edge-null'", [str(tmp_path/"result/events.parquet")]).fetchone()[0] is None
        assert c.execute("SELECT revenue_usd FROM read_parquet(?) WHERE event_id='edge-negative'", [str(tmp_path/"result/events.parquet")]).fetchone()[0] == -.02


def test_failure_has_no_published_manifest(tmp_path):
    data = sources(tmp_path)
    bad_mapping = {**MAPPING, "events": {**MAPPING["events"], "event_id": "absent"}}
    with pytest.raises(IngestError, match="MAPPED_COLUMN_MISSING"):
        canonicalize(data, bad_mapping, tmp_path/"failed")
    assert not (tmp_path/"failed/manifest.json").exists()
    data[0]["sha256"] = "0"*64
    with pytest.raises(IngestError, match="SOURCE_CHECKSUM_MISMATCH"):
        canonicalize(data, MAPPING, tmp_path/"bad-hash")
    assert not (tmp_path/"bad-hash").exists()


def test_user_conflict_poison_and_unknown_ad_format(tmp_path):
    user = json.loads((HAND/"users.json").read_text())[0]
    event = json.loads((HAND/"events.json").read_text())[0]
    # Two differing install records for one user: neither is selected as the winner.
    data = [write_source(tmp_path, "users", [user, {**user, "country": "XX"}]),
            write_source(tmp_path, "events", [{**event, "user_id": user["user_id"], "ad_format": "new-format"}])]
    result = canonicalize(data, MAPPING, tmp_path/"result")
    assert result["counts"]["users"]["quarantined_keys"] == 1
    assert result["counts"]["users"]["retained_rows"] == 0
    assert result["counts"]["events"]["link_rejections"] == {"unmatched_user": 1}


def test_missing_timezone_nonfinite_revenue_and_duplicate_header(tmp_path):
    event = json.loads((HAND/"events.json").read_text())[-1]
    extras = [{**event, "event_id": "no-tz", "event_time": "2026-01-01T01:00:00"},
              {**event, "event_id": "nan", "revenue_usd": "NaN"}]
    data = sources(tmp_path, extras=extras)
    result = canonicalize(data, MAPPING, tmp_path/"result")
    assert result["counts"]["events"]["reasons"]["invalid_event_time"] == 1
    assert result["counts"]["events"]["reasons"]["invalid_revenue_usd"] == 1
    bad_header = tmp_path/"duplicate.csv"
    bad_header.write_text("user_id,user_id\nu1,u2\n")
    data[0] = {"role": "users", "format": "csv", "path": str(bad_header), "sha256": file_hash(bad_header)}
    with pytest.raises(IngestError, match="AMBIGUOUS_SOURCE_COLUMNS"):
        canonicalize(data, MAPPING, tmp_path/"bad-header")
    assert not (tmp_path/"bad-header/manifest.json").exists()


def test_partial_artifact_failure_never_publishes_manifest(tmp_path, monkeypatch):
    import server.analysis.ingest as ingest
    data = sources(tmp_path)
    original_hash = ingest.file_hash
    def fail_after_first_artifact(path):
        if Path(path) == tmp_path/"result/events.parquet":
            raise OSError("synthetic artifact verification failure")
        return original_hash(path)
    monkeypatch.setattr(ingest, "file_hash", fail_after_first_artifact)
    with pytest.raises(OSError):
        canonicalize(data, MAPPING, tmp_path/"result")
    assert (tmp_path/"result/users.parquet").exists()
    assert not (tmp_path/"result/manifest.json").exists()


def test_unknown_format_is_explicit_and_native_timezone_normalizes(tmp_path):
    user = json.loads((HAND/"users.json").read_text())[0]
    event = json.loads((HAND/"events.json").read_text())[-1]
    event = {**event, "event_id": "unknown-format", "ad_format": "new-format",
             "event_time": "2026-01-01T09:00:00+08:00", "available_at": "2026-01-01T01:00:00Z"}
    result = canonicalize([write_source(tmp_path,"users",[user]), write_source(tmp_path,"events",[event])],
                          MAPPING, tmp_path/"result")
    with duckdb.connect() as c:
        c.execute("SET TimeZone='UTC'")
        row = c.execute("SELECT ad_format,strftime(event_time,'%Y-%m-%dT%H:%M:%SZ') FROM read_parquet(?)",
                        [str(tmp_path/"result/events.parquet")]).fetchone()
    assert row == ("unknown", "2026-01-01T01:00:00Z")


def test_multi_row_group_disk_backed_ingest(tmp_path):
    from scripts.generate_fixture import generate
    generated = generate(tmp_path/"source", 1000, 150000, seed=42)
    data, mapping = [], {}
    for role in ("users", "events"):
        path = generated/f"{role}.csv"
        with path.open() as stream:
            fields = next(csv.reader(stream))
        mapping[role] = {name: name for name in fields}
        data.append({"path": str(path), "role": role, "format": "csv", "sha256": file_hash(path)})
    result = canonicalize(data, mapping, tmp_path/"result", memory_limit="128MB", threads=2)
    assert result["counts"]["events"]["retained_rows"] == 150000
    assert result["counts"]["users"]["retained_rows"] == 1000
    with duckdb.connect() as c:
        assert c.execute("SELECT count(DISTINCT row_group_id) FROM parquet_metadata(?)",
                         [str(tmp_path/"result/events.parquet")]).fetchone()[0] >= 2
    assert all(file_hash(source["path"]) == source["sha256"] for source in data)

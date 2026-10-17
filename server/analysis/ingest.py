"""Disk-backed canonicalization with auditable rejection and conflict quarantine."""
import csv
import hashlib
import json
import os
from pathlib import Path

import duckdb
from server.analysis.connection import connect

USER_TYPES = {"app_id": "VARCHAR", "user_id": "VARCHAR", "installed_at": "TIMESTAMPTZ",
              "platform": "VARCHAR", "country": "VARCHAR", "acquisition_source": "VARCHAR",
              "campaign_id": "VARCHAR", "app_version_at_install": "VARCHAR"}
EVENT_TYPES = {"app_id": "VARCHAR", "user_id": "VARCHAR", "event_id": "VARCHAR", "event_name": "VARCHAR",
               "event_time": "TIMESTAMPTZ", "available_at": "TIMESTAMPTZ", "session_id": "VARCHAR",
               "source_sequence": "BIGINT", "ad_format": "VARCHAR", "revenue_usd": "DOUBLE",
               "engaged_seconds": "DOUBLE", "level_id": "VARCHAR", "level_index": "BIGINT",
               "attempt_id": "VARCHAR", "level_mode": "VARCHAR", "difficulty": "VARCHAR",
               "revive_used": "BOOLEAN", "booster_used": "BOOLEAN", "app_version": "VARCHAR"}
REQUIRED = {"users": {"app_id","user_id","installed_at","platform"},
            "events": {"app_id","user_id","event_id","event_name","event_time"}}


class IngestError(Exception):
    pass


def ident(value):
    return '"'+value.replace('"', '""')+'"'


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def time_valid(column):
    # Require an explicit timezone, including DuckDB's string form for typed TIMESTAMPTZ Parquet.
    pattern = r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}(:?[0-9]{2})?)"
    return f"(regexp_full_match({ident(column)}, '{pattern}') AND try_cast({ident(column)} AS TIMESTAMPTZ) IS NOT NULL)"


def canonicalize(sources, mapping, destination, *, memory_limit="512MB", threads=2):
    """sources: verified local files with role/format/path/sha256. Output directory must not exist."""
    destination = Path(destination)
    normalized_sources = []
    for source in sources:
        path = Path(source["path"]).resolve(strict=True)
        if not path.is_file() or any(char in str(path) for char in '*?[') or source["role"] not in REQUIRED or source["format"] not in ("csv", "parquet"):
            raise IngestError("INVALID_SOURCE")
        digest = file_hash(path)
        if digest != source["sha256"]:
            raise IngestError("SOURCE_CHECKSUM_MISMATCH")
        normalized_sources.append({**source, "path": str(path)})
    if sum(source["role"] == "users" for source in sources) != 1 or not any(source["role"] == "events" for source in sources):
        raise IngestError("USERS_AND_EVENTS_REQUIRED")
    for role, types in (("users", USER_TYPES), ("events", EVENT_TYPES)):
        fields = mapping.get(role, {})
        if not REQUIRED[role].issubset(fields) or not set(fields).issubset(types):
            raise IngestError("INVALID_MAPPING")
    destination.mkdir(parents=True, exist_ok=False)
    connection = connect(str(destination/"work.duckdb"), config={
        "memory_limit": memory_limit, "threads": threads, "preserve_insertion_order": False,
        "autoload_known_extensions": False, "autoinstall_known_extensions": False})
    try:
        connection.execute("SET TimeZone='UTC'")
        connection.execute("SET temp_directory=?", [str(destination/"spill")])
        for role, types in (("users", USER_TYPES), ("events", EVENT_TYPES)):
            connection.execute(f"CREATE TABLE raw_{role} ({','.join(ident(name)+' VARCHAR' for name in types)})")
        for source in normalized_sources:
            role = source["role"]
            types = USER_TYPES if role == "users" else EVENT_TYPES
            if source["format"] == "csv":
                try:
                    with Path(source["path"]).open(encoding="utf-8-sig", newline="") as stream:
                        header = next(csv.reader(stream))
                except (csv.Error, UnicodeError, StopIteration):
                    raise IngestError("INVALID_CSV_HEADER") from None
                if not header or len({name.lower() for name in header}) != len(header):
                    raise IngestError("AMBIGUOUS_SOURCE_COLUMNS")
            reader = "read_csv(?, header=true, all_varchar=true, strict_mode=true, ignore_errors=false)" if source["format"] == "csv" else "read_parquet(?)"
            relation = connection.sql(f"SELECT * FROM {reader}", params=[source["path"]])
            columns = relation.columns
            if len(set(name.lower() for name in columns)) != len(columns):
                raise IngestError("AMBIGUOUS_SOURCE_COLUMNS")
            if not set(mapping[role].values()).issubset(columns):
                raise IngestError("MAPPED_COLUMN_MISSING")
            expressions = [f"NULLIF(CAST({ident(mapping[role][name])} AS VARCHAR),'')" if name in mapping[role]
                           else "NULL::VARCHAR" for name in types]
            connection.execute(f"INSERT INTO raw_{role} SELECT {','.join(expressions)} FROM {reader}", [source["path"]])
        stats = {}
        for role, types in (("users", USER_TYPES), ("events", EVENT_TYPES)):
            checks = []
            for name in REQUIRED[role]:
                checks.append((f"{ident(name)} IS NULL OR {ident(name)}=''", f"missing_{name}"))
            for name, dtype in types.items():
                if dtype == "VARCHAR" and name not in ("ad_format", "event_name", "platform"):
                    checks.append((f"length({ident(name)})>256", f"invalid_{name}"))
                if dtype == "TIMESTAMPTZ":
                    checks.append((f"{ident(name)} IS NOT NULL AND NOT coalesce({time_valid(name)},false)", f"invalid_{name}"))
                elif dtype == "DOUBLE":
                    checks.append((f"{ident(name)} IS NOT NULL AND (try_cast({ident(name)} AS DOUBLE) IS NULL OR NOT isfinite(try_cast({ident(name)} AS DOUBLE)))", f"invalid_{name}"))
                elif dtype == "BIGINT":
                    checks.append((f"{ident(name)} IS NOT NULL AND (NOT regexp_full_match({ident(name)},'[0-9]+') OR try_cast({ident(name)} AS BIGINT) IS NULL)", f"invalid_{name}"))
                elif dtype == "BOOLEAN":
                    checks.append((f"{ident(name)} IS NOT NULL AND try_cast({ident(name)} AS BOOLEAN) IS NULL", f"invalid_{name}"))
            if role == "users":
                checks.append(("platform NOT IN ('android','ios')", "invalid_platform"))
            else:
                checks += [("event_name NOT IN ('ad_impression','session_start','session_end','level_start','level_complete','level_fail')", "unsupported_event"),
                           ("try_cast(engaged_seconds AS DOUBLE)<0", "negative_engaged_seconds"),
                           ("try_cast(available_at AS TIMESTAMPTZ)<try_cast(event_time AS TIMESTAMPTZ)", "available_before_event")]
            reason_sql = "list_filter(["+",".join(f"CASE WHEN {check} THEN '{reason}' END" for check, reason in checks)+"], x -> x IS NOT NULL)"
            connection.execute(f"CREATE TABLE checked_{role} AS SELECT *, {reason_sql} AS reasons FROM raw_{role}")
            casts = ",".join(f"try_cast({ident(name)} AS {dtype}) AS {ident(name)}" for name,dtype in types.items())
            connection.execute(f"CREATE TABLE typed_{role} AS SELECT {casts} FROM checked_{role} WHERE len(reasons)=0")
            keys = "app_id,user_id" if role == "users" else "app_id,event_id"
            # A key with an invalid row is poisoned too; never retain an arbitrary valid sibling.
            connection.execute(f"""CREATE TABLE conflict_{role} AS
                SELECT {keys} FROM (SELECT DISTINCT * FROM typed_{role}) GROUP BY {keys} HAVING count(*)>1
                UNION SELECT DISTINCT {keys} FROM checked_{role} WHERE len(reasons)>0
            """)
            connection.execute(f"CREATE TABLE unique_{role} AS SELECT DISTINCT t.* FROM typed_{role} t ANTI JOIN conflict_{role} USING ({keys})")
            stats[role] = {
                "input_rows": connection.execute(f"SELECT count(*) FROM raw_{role}").fetchone()[0],
                "invalid_rows": connection.execute(f"SELECT count(*) FROM checked_{role} WHERE len(reasons)>0").fetchone()[0],
                "duplicate_rows": connection.execute(f"SELECT (SELECT count(*) FROM typed_{role})-(SELECT count(*) FROM (SELECT DISTINCT * FROM typed_{role}))").fetchone()[0],
                "quarantined_keys": connection.execute(f"SELECT count(*) FROM conflict_{role}").fetchone()[0],
            }
            stats[role]["reasons"] = dict(connection.execute(f"SELECT reason,count(*) FROM (SELECT unnest(reasons) reason FROM checked_{role}) GROUP BY reason").fetchall())
        connection.execute("CREATE TABLE users AS SELECT * FROM unique_users")
        connection.execute("""CREATE TABLE event_links AS SELECT e.*,
            CASE WHEN u.user_id IS NULL THEN 'unmatched_user'
                 WHEN e.event_time<u.installed_at THEN 'before_install' END AS rejection
            FROM unique_events e LEFT JOIN users u USING(app_id,user_id)""")
        connection.execute("""CREATE TABLE events AS SELECT * EXCLUDE(rejection) REPLACE (
            CASE WHEN ad_format IS NULL THEN NULL
                 WHEN ad_format IN ('rewarded','interstitial','banner','app_open','native','other','unknown') THEN ad_format
                 ELSE 'unknown' END AS ad_format)
            FROM event_links WHERE rejection IS NULL""")
        stats["events"]["link_rejections"] = dict(connection.execute("SELECT rejection,count(*) FROM event_links WHERE rejection IS NOT NULL GROUP BY rejection").fetchall())
        artifacts = []
        tables = ["users", "events", "conflict_users", "conflict_events", "rejected_users", "rejected_events", "rejected_links"]
        connection.execute("CREATE VIEW rejected_users AS SELECT * FROM checked_users WHERE len(reasons)>0")
        connection.execute("CREATE VIEW rejected_events AS SELECT * FROM checked_events WHERE len(reasons)>0")
        connection.execute("CREATE VIEW rejected_links AS SELECT * FROM event_links WHERE rejection IS NOT NULL")
        # Keep all conflicting source values for audit, not just their IDs.
        for role in ("users", "events"):
            keys = "app_id,user_id" if role == "users" else "app_id,event_id"
            table = f"conflicting_{role}_rows"
            connection.execute(f"CREATE TABLE {table} AS SELECT r.* FROM raw_{role} r SEMI JOIN conflict_{role} USING({keys})")
            tables.append(table)
        for table in tables:
            path = destination/f"{table}.parquet"
            connection.execute(f"COPY (SELECT * FROM {ident(table)} ORDER BY ALL) TO ? (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 65536)", [str(path)])
            artifacts.append({"name": table, "path": path.name, "sha256": file_hash(path),
                              "size_bytes": path.stat().st_size, "rows": connection.execute(f"SELECT count(*) FROM {ident(table)}").fetchone()[0]})
        for role in ("users", "events"):
            stats[role]["retained_rows"] = connection.execute(f"SELECT count(*) FROM {role}").fetchone()[0]
        # Verify input files did not change while being processed; publish manifest only at the end.
        for source in normalized_sources:
            if file_hash(source["path"]) != source["sha256"]:
                raise IngestError("SOURCE_CHANGED_DURING_INGEST")
        manifest = {"schema_version": "1.0", "ingest_version": "2.0-casual-game", "stage": "normalized", "sources": normalized_sources, "mapping": mapping,
                    "artifacts": artifacts, "counts": stats, "duckdb_version": duckdb.__version__}
        partial = destination/"manifest.partial.json"
        with partial.open("x") as stream:
            json.dump(manifest, stream, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(partial, destination/"manifest.json")
        partial.unlink()
        return manifest
    except duckdb.Error:
        raise IngestError("INGEST_QUERY_OR_FORMAT_FAILED") from None
    finally:
        connection.close()

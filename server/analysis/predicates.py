"""Schema-constrained monotone predicates. SQL identifiers are never supplied by candidates."""
import json
import math
import os
from pathlib import Path
from itertools import groupby
from collections import Counter
from tempfile import TemporaryDirectory

from server.analysis.connection import connect
from jsonschema import Draft202012Validator

from server.analysis.ingest import IngestError, file_hash
from server.analysis.sequences import first_sequence_trigger

CAPABILITIES = {"count": "ad_frequency", "revenue_sum": "revenue_trigger",
                "session_count": "session_count", "engaged_seconds": "engaged_seconds"}
EVENTS = {"count": "ad_impression", "revenue_sum": "ad_impression",
          "session_count": "session_start", "engaged_seconds": "session_end"}


def validate_candidate(candidate):
    schema = json.loads((Path(__file__).resolve().parents[2]/"contracts/schema.json").read_text())
    if not Draft202012Validator({**schema, "$ref": "#/$defs/candidate"}).is_valid(candidate):
        raise IngestError("INVALID_CANDIDATE")
    predicate = candidate["predicate"]
    if not math.isfinite(candidate["window_hours"]):
        raise IngestError("INVALID_CANDIDATE")
    if predicate["op"] == "sequence":
        if not math.isfinite(predicate["max_gap_seconds"]):
            raise IngestError("INVALID_CANDIDATE")
        return []
    atoms = predicate["clauses"] if predicate["op"] in ("and", "or") else [predicate]
    for atom in atoms:
        if not math.isfinite(atom["threshold"]):
            raise IngestError("INVALID_CANDIDATE")
        if atom["op"] in ("count", "session_count") and not float(atom["threshold"]).is_integer():
            raise IngestError("INTEGER_COUNT_REQUIRED")
        if atom.get("event_name", EVENTS[atom["op"]]) != EVENTS[atom["op"]]:
            raise IngestError("INCOMPATIBLE_EVENT_NAME")
        if "ad_format" in atom and atom["op"] not in ("count", "revenue_sum"):
            raise IngestError("INCOMPATIBLE_AD_FORMAT")
    return atoms


def evaluate_candidates(normalized_dir, feature_dir, candidates, destination, *, holdout_targets=None):
    normalized_dir, feature_dir, destination = map(Path, (normalized_dir, feature_dir, destination))
    if not isinstance(candidates, list) or not candidates or len(candidates) > 2000:
        raise IngestError("INVALID_CANDIDATE_BATCH")
    atoms_by_id = [(candidate, validate_candidate(candidate)) for candidate in candidates]
    # min qualifying time over the feature horizon is inside a candidate's
    # prefix window iff that candidate has any qualifying time in the window.
    # Thus thresholds share the first time, while window cutoffs remain separate.
    def atom_key(candidate,atom):
        return (atom['op'],atom.get('ad_format','all'),atom['threshold'])
    remaining=Counter(atom_key(candidate,atom) for candidate,atoms in atoms_by_id for atom in atoms)
    reusable={key:index for index,(key,count) in enumerate(remaining.items()) if count>1}
    if len({candidate["candidate_id"] for candidate in candidates}) != len(candidates):
        raise IngestError("DUPLICATE_CANDIDATE_ID")
    manifest = json.loads((feature_dir/"manifest.json").read_text())
    if manifest["definition"]["source_manifest_sha256"] != file_hash(normalized_dir/"manifest.json"):
        raise IngestError("FEATURE_SOURCE_MISMATCH")
    normalized = json.loads((normalized_dir/"manifest.json").read_text())
    scope=None
    if holdout_targets is not None:
        holdout_targets=Path(holdout_targets)
        target_manifest=json.loads((holdout_targets/'manifest.json').read_text())
        if target_manifest['source_manifest_sha256']!=file_hash(normalized_dir/'manifest.json'):
            raise IngestError('PREDICATE_SCOPE_SOURCE_MISMATCH')
        scope={'split':'holdout','is_mature':True,'split_id':target_manifest['split_id'],
               'target_manifest_sha256':file_hash(holdout_targets/'manifest.json')}
    verified = []
    inputs = [(feature_dir, manifest["artifacts"], "timeline"),
              (normalized_dir, normalized["artifacts"], "users")]
    if scope is not None:inputs.append((holdout_targets,target_manifest['artifacts'],'targets'))
    has_sequences = any(candidate["predicate"]["op"] == "sequence" for candidate in candidates)
    if has_sequences:
        inputs.append((normalized_dir, normalized["artifacts"], "events"))
    for root, records, name in inputs:
        matched = [record for record in records if record["name"] == name]
        if len(matched) != 1 or matched[0]["path"] != name+".parquet":
            raise IngestError("ARTIFACT_MANIFEST_INVALID")
        path, digest = root/matched[0]["path"], matched[0]["sha256"]
        if path.resolve().parent != root.resolve() or file_hash(path) != digest:
            raise IngestError("ARTIFACT_CHECKSUM_MISMATCH")
        verified.append((path, digest))
    for candidate, atoms in atoms_by_id:
        if candidate["window_hours"] > max(manifest["definition"]["windows_hours"]):
            raise IngestError("FEATURE_HORIZON_INSUFFICIENT")
        for atom in atoms:
            if not manifest["capabilities"][CAPABILITIES[atom["op"]]]["enabled"]:
                raise IngestError("FEATURE_CAPABILITY_DISABLED")
    destination.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix='trigger-parts-', dir=destination) as parts_dir, \
            connect(str(destination/"work.duckdb"), config={"memory_limit": "256MB", "threads": 2}) as c:
        c.execute("SET TimeZone='UTC'")
        c.execute('SET preserve_insertion_order=true')
        c.read_parquet(str(feature_dir/"timeline.parquet")).create_view("timeline")
        c.read_parquet(str(normalized_dir/"users.parquet")).create_view("all_users")
        if scope is None:
            c.execute('''CREATE TABLE users AS SELECT *,
                row_number() OVER (ORDER BY app_id,user_id)-1 evaluation_index FROM all_users''')
        else:
            c.read_parquet(str(holdout_targets/'targets.parquet')).create_view('scope_targets')
            c.execute("""CREATE TABLE users AS SELECT u.*,
                row_number() OVER (ORDER BY u.app_id,u.user_id)-1 evaluation_index FROM all_users u
                SEMI JOIN (SELECT app_id,user_id FROM scope_targets WHERE split='holdout' AND is_mature) t
                USING(app_id,user_id)""")
        # Reuse the immutable join across all thresholds and compound clauses.
        # Sorted dimensions let DuckDB skip unrelated metric/format blocks.
        c.execute('''CREATE TEMP TABLE evaluation_timeline AS
            SELECT l.metric,l.ad_format,l.available_at,l.value,u.evaluation_index,u.installed_at
            FROM timeline l JOIN users u USING(app_id,user_id)
            ORDER BY metric,ad_format,evaluation_index,available_at''')
        event_names=set()
        if has_sequences:
            c.read_parquet(str(normalized_dir/"events.parquet")).create_view("events")
            event_names={row[0] for row in c.execute('SELECT DISTINCT event_name FROM events').fetchall()}
        c.execute("CREATE TEMP TABLE triggers(candidate_id VARCHAR,app_id VARCHAR,user_id VARCHAR,triggered_at TIMESTAMPTZ)")
        parts=[]
        count=0
        def flush_candidate(identity, query=None, parameters=None):
            nonlocal count
            # Internal filenames only: candidate IDs are data, never paths.
            part=Path(parts_dir)/f'{len(parts):04d}.parquet'
            rows=c.execute('COPY ('+(query or 'SELECT * FROM triggers')+' ORDER BY ALL) TO $output_path '
                           '(FORMAT PARQUET, COMPRESSION ZSTD)',
                           {**(parameters or {}),'output_path':str(part)}).fetchone()[0]
            count+=rows
            parts.append((identity,str(part)))
            if query is None:
                # Only sequence evaluation requires a Python-fed buffer. Atomic
                # and boolean queries stream directly to their ordered part.
                c.execute('DROP TABLE triggers')
                c.execute('CREATE TEMP TABLE triggers(candidate_id VARCHAR,app_id VARCHAR,'
                          'user_id VARCHAR,triggered_at TIMESTAMPTZ)')
        sequence_phase=False
        cached_atoms={}
        for candidate, atoms in sorted(atoms_by_id,key=lambda item:item[0]['predicate']['op']=='sequence'):
            predicate = candidate["predicate"]
            if predicate["op"] == "sequence":
                if not sequence_phase:
                    c.execute('DROP TABLE evaluation_timeline')
                    c.execute('DROP TABLE IF EXISTS atom_0')
                    c.execute('DROP TABLE IF EXISTS atom_1')
                    c.execute('CHECKPOINT')
                    sequence_phase=True
                if not set(predicate['steps']).issubset(event_names):
                    continue  # Still an evaluated candidate, with no possible trigger.
                # Separate cursor allows bounded read batches while writing results.
                reader = c.cursor()
                try:
                    reader.execute("""SELECT app_id,user_id,event_time,source_sequence,event_name,event_id
                        FROM events JOIN users USING(app_id,user_id)
                        WHERE event_name IN (?,?) AND event_time>=installed_at
                          AND event_time<installed_at+?*INTERVAL '1 hour'
                          AND event_time<=CAST(? AS TIMESTAMPTZ)
                        ORDER BY app_id,user_id,event_time""", [*predicate["steps"], candidate["window_hours"],
                            manifest["definition"]["export_metadata"]["exported_at"]])
                    def records():
                        while batch := reader.fetchmany(4096):
                            yield from batch
                    pending = []
                    for (app_id, user_id), rows in groupby(records(), key=lambda row: (row[0], row[1])):
                        triggered_at = first_sequence_trigger((row[2:] for row in rows), predicate["steps"],
                                                              predicate["max_gap_seconds"], predicate["repeats"])
                        if triggered_at is not None:
                            pending.append((candidate["candidate_id"], app_id, user_id, triggered_at))
                        if len(pending) >= 1000:
                            c.executemany("INSERT INTO triggers VALUES (?,?,?,?)", pending)
                            pending.clear()
                    if pending:
                        c.executemany("INSERT INTO triggers VALUES (?,?,?,?)", pending)
                finally:
                    reader.close()
                flush_candidate(candidate['candidate_id'])
                continue
            atom_tables=[]
            for index, atom in enumerate(atoms):
                key=atom_key(candidate,atom)
                table=cached_atoms.get(key)
                if table is not None:
                    atom_tables.append(f"(SELECT evaluation_index,triggered_at FROM {table} WHERE triggered_at<installed_at+$window*INTERVAL '1 hour')")
                    continue
                table=f'reused_atom_{reusable[key]}' if key in reusable else f'atom_{index}'
                c.execute(f"""CREATE OR REPLACE TEMP TABLE {table} AS
                    SELECT evaluation_index,installed_at,min(available_at) triggered_at
                    FROM evaluation_timeline
                    WHERE metric=? AND ad_format=? AND value>=?
                    GROUP BY evaluation_index,installed_at""", [atom["op"], atom.get("ad_format", "all"),
                                                 atom["threshold"]])
                atom_tables.append(f"(SELECT evaluation_index,triggered_at FROM {table} WHERE triggered_at<installed_at+$window*INTERVAL '1 hour')")
                if key in reusable:cached_atoms[key]=table
            op = candidate["predicate"]["op"]
            if op == "and":
                query = f"SELECT evaluation_index,greatest(a.triggered_at,b.triggered_at) triggered_at FROM {atom_tables[0]} a JOIN {atom_tables[1]} b USING(evaluation_index)"
            elif op == "or":
                query = f"SELECT evaluation_index,min(triggered_at) triggered_at FROM (SELECT * FROM {atom_tables[0]} UNION ALL SELECT * FROM {atom_tables[1]}) GROUP BY evaluation_index"
            else:
                query = f"SELECT * FROM {atom_tables[0]}"
            flush_candidate(candidate['candidate_id'],
                'SELECT $identity AS candidate_id,u.app_id,u.user_id,r.triggered_at FROM ('+query+') r '
                'JOIN users u USING(evaluation_index)',
                {'identity':candidate['candidate_id'],'window':candidate['window_hours']})
            # Release each exact intermediate after its final consumer. Tables
            # are connection-local and DuckDB remains under its original quota.
            for atom in atoms:
                key=atom_key(candidate,atom);remaining[key]-=1
                if remaining[key]==0 and key in cached_atoms:
                    c.execute(f'DROP TABLE {cached_atoms.pop(key)}')
        path = destination/"triggers.parquet"
        if parts:
            # Each part is sorted and contains exactly one candidate. The ordered
            # file list plus insertion-order-preserving scan/COPY avoids sorting
            # the entire many-million-row result a second time.
            c.read_parquet([part for _,part in sorted(parts)]).create_view('ordered_parts')
            c.execute('COPY (SELECT candidate_id,app_id,user_id,triggered_at '
                      'FROM ordered_parts) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)',[str(path)])
        else:
            c.execute('COPY triggers TO ? (FORMAT PARQUET, COMPRESSION ZSTD)',[str(path)])
    for source, digest in verified:
        if file_hash(source) != digest:
            raise IngestError("SOURCE_CHANGED_DURING_EVALUATION")
    if scope is not None and file_hash(holdout_targets/'manifest.json')!=scope['target_manifest_sha256']:
        raise IngestError('SOURCE_CHANGED_DURING_EVALUATION')
    output = {"schema_version": "1.0", "stage": "predicates", "evaluator_version": "1.7",
              "feature_id": manifest["feature_id"], "synthetic": manifest["synthetic"],
              "candidates": candidates, "artifacts": [{"name": "triggers", "path": path.name,
              "sha256": file_hash(path), "size_bytes": path.stat().st_size, "rows": count}]}
    if scope is not None:output.update(evaluation_scope=scope)
    partial = destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(output, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, destination/"manifest.json")
    partial.unlink()
    return output

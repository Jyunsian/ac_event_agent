"""Server-owned eligibility; identities never go to the model or report."""
import hashlib
import json
import tempfile
from pathlib import Path
from server.analysis.connection import connect
from sqlalchemy import text
from server.analysis.freeze import load_frozen
from server.analysis.ingest import IngestError,file_hash
from server.analysis.validation import verified_artifact
from server.jobs import JobQueue
from server.storage import ObjectManifest

POLICY_LOCK=13371329


def backfill_exposed_populations(engine,storage,workspace):
    """Index pre-policy reports using only verified, committed normalized files."""
    with engine.connect() as c:
        missing=c.execute(text('''SELECT DISTINCT e.dataset_id FROM validation_exposures e
          LEFT JOIN validation_populations p ON e.dataset_id=p.dataset_id WHERE p.dataset_id IS NULL''')).scalars().all()
    for dataset_id in missing:
        with engine.connect() as c:
            manifests=c.execute(text('''SELECT s.manifest FROM stage_checkpoints s JOIN runs r ON r.id=s.run_id
              WHERE r.dataset_id=:ds AND s.stage='normalized' ORDER BY s.created_at'''),{'ds':dataset_id}).scalars().all()
        usable=[]
        for manifest in manifests:
            entries={entry['path']:entry['object'] for entry in manifest['files']}
            if 'users.parquet' in entries and 'manifest.json' in entries:usable.append(entries)
        if not usable:continue  # Reservation will explicitly deny unknown populations.
        if len({entries['users.parquet']['sha256'] for entries in usable})!=1:
            raise IngestError('VALIDATION_POPULATION_BACKFILL_AMBIGUOUS')
        with tempfile.TemporaryDirectory(prefix='population-backfill-',dir=workspace) as directory:
            root=Path(directory)
            for name in ('users.parquet','manifest.json'):
                storage.download_file(ObjectManifest(**usable[0][name]),root/name)
            register_population(engine,dataset_id,root)


def register_population(engine,dataset_id,normalized):
    normalized=Path(normalized)
    manifest=json.loads((normalized/'manifest.json').read_text())
    users,sha=verified_artifact(normalized,manifest,'users')
    with engine.begin() as c:
        # Same dataset serializes enrollment without locking unrelated datasets.
        c.execute(text('SELECT id FROM datasets WHERE id=:id FOR UPDATE'),{'id':dataset_id}).scalar_one()
        previous=c.execute(text('SELECT users_sha256 FROM validation_populations WHERE dataset_id=:id'),{'id':dataset_id}).scalar_one_or_none()
        if previous is not None:
            if previous!=sha:raise IngestError('VALIDATION_POPULATION_CHANGED')
            return
        with connect(config={'memory_limit':'256MB','threads':2}) as db:
            db.read_parquet(str(users)).create_view('users')
            count=db.execute('SELECT count(*) FROM users').fetchone()[0]
            c.execute(text('INSERT INTO validation_populations(dataset_id,users_sha256,user_count) VALUES(:id,:sha,:n)'),{'id':dataset_id,'sha':sha,'n':count})
            cursor=db.execute('SELECT app_id,user_id FROM users ORDER BY app_id,user_id')
            while batch:=cursor.fetchmany(2000):
                rows=[{'id':dataset_id,'h':hashlib.sha256(json.dumps([app,user],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()} for app,user in batch]
                c.execute(text('INSERT INTO validation_population_members(dataset_id,user_hash) VALUES(:id,:h)'),rows)
        if file_hash(users)!=sha:raise IngestError('VALIDATION_POPULATION_CHANGED')


def reserve_validation(engine,lease,dataset_id,frozen_dir,frozen_sha256):
    frozen_path=Path(frozen_dir)/'frozen.json'
    if file_hash(frozen_path)!=frozen_sha256:raise IngestError('FROZEN_CONTRACT_CHANGED')
    header=json.loads(frozen_path.read_text())
    if header.get('analysis_version')=='4.0-time-aware':
        from server.analysis.v4_search import load_frozen as load_v4
        frozen=load_v4(frozen_dir,frozen_sha256)
    elif header.get('analysis_version')=='3.0-casual-game':
        from server.analysis.casual_freeze import load_casual_freeze
        frozen=load_casual_freeze(frozen_dir,frozen_sha256)
    else:frozen=load_frozen(frozen_dir,frozen_sha256)
    with engine.begin() as c:
        owned=JobQueue(engine)._owned(c,lease)
        if owned['run_id']!=lease.run_id:raise IngestError('VALIDATION_LEASE_RUN_MISMATCH')
        # Disclosure and reservation use the same transaction lock. If freezing
        # wins, later disclosure cannot change these already-fixed candidates.
        c.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':POLICY_LOCK})
        existing=c.execute(text('SELECT * FROM validation_reservations WHERE run_id=:run'),{'run':lease.run_id}).mappings().one_or_none()
        if existing:
            if existing['frozen_sha256']!=frozen_sha256 or existing['split_id']!=frozen['split_id'] or existing['dataset_id']!=dataset_id:
                raise IngestError('VALIDATION_RESERVATION_CHANGED')
            return {k:existing[k] for k in ('eligible','reasons','policy_version','frozen_sha256','split_id')}
        reasons=[]
        kind=c.execute(text('SELECT kind FROM runs WHERE id=:id AND dataset_id=:ds'),{'id':lease.run_id,'ds':dataset_id}).scalar_one()
        if kind!='baseline':reasons.append('FOLLOWUP_IS_EXPLORATORY')
        if c.execute(text('SELECT EXISTS(SELECT 1 FROM validation_exposures WHERE dataset_id=:ds)'),{'ds':dataset_id}).scalar_one():
            reasons.append('DATASET_ALREADY_EXPOSED')
        # Legacy exposed datasets without verified membership cannot be assumed
        # disjoint. They must be indexed before granting new independent labels.
        if c.execute(text('SELECT EXISTS(SELECT 1 FROM validation_exposures e LEFT JOIN validation_populations p ON p.dataset_id=e.dataset_id WHERE p.dataset_id IS NULL)')).scalar_one():
            reasons.append('EXPOSED_POPULATION_UNKNOWN')
        overlap=c.execute(text('''SELECT EXISTS(SELECT 1 FROM validation_population_members current
          JOIN validation_population_members previous ON current.user_hash=previous.user_hash
          JOIN validation_exposures e ON e.dataset_id=previous.dataset_id
          WHERE current.dataset_id=:ds)'''),{'ds':dataset_id}).scalar_one()
        if overlap:reasons.append('USERS_OVERLAP_EXPOSED_DATA')
        JobQueue(engine)._owned(c,lease)
        result={'eligible':not reasons,'reasons':reasons,'policy_version':'1.0','frozen_sha256':frozen_sha256,'split_id':frozen['split_id']}
        c.execute(text('''INSERT INTO validation_reservations(run_id,dataset_id,split_id,frozen_sha256,eligible,reasons)
          VALUES(:run,:ds,:split,:sha,:eligible,CAST(:reasons AS jsonb))'''),
          {'run':lease.run_id,'ds':dataset_id,'split':frozen['split_id'],'sha':frozen_sha256,'eligible':not reasons,'reasons':json.dumps(reasons)})
        c.execute(text("UPDATE runs SET split_id=:split,evidence_status=CASE WHEN :eligible THEN evidence_status ELSE 'exploratory' END WHERE id=:id"),
                  {'split':frozen['split_id'],'eligible':not reasons,'id':lease.run_id})
        return result

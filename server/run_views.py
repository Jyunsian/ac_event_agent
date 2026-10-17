"""Durable run read models and explicit, fenced technical retries."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import select, text, tuple_
from server.uploads import APIError

RETRY_CODES = {"TASK_TIMEOUT", "COMPUTE_PROCESS_EXITED", "WORKER_SHUTDOWN", "RETRY_LIMIT",
               "DATABASE_NOT_CONFIGURED", "STORAGE_UNAVAILABLE", "STORAGE_SERVICE_ERROR",
               "STORAGE_ACCESS_DENIED", "WORKER_INTERNAL_ERROR", "COMPUTE_FAILED"}


def run_view(service, run_id, requested_version=None, artifact_id=None):
    with service.engine.connect() as c:
        run = dict(service.row(c, "runs", run_id))
        dataset = service.row(c, "datasets", run["dataset_id"])
        project = service.row(c, "projects", dataset["project_id"])
        jobs, reports, artifacts = [service.tables[name] for name in ("jobs", "report_versions", "artifacts")]
        job = c.execute(select(jobs).where(jobs.c.run_id == run_id, jobs.c.queue == "compute")).mappings().one_or_none()
        versions = c.execute(select(reports).where(reports.c.run_id == run_id).order_by(reports.c.version.desc())).mappings().all()
        refs = c.execute(select(artifacts).where(artifacts.c.run_id == run_id)).mappings().all()
    ready_version = None
    ready_artifact = None
    for version in versions:
        if requested_version is not None and version['version'] != requested_version:
            continue
        model = next((a for a in refs if a["id"] == version["artifact_id"] and a["kind"] == "report_json"), None)
        if model and all(sum(a["attempt_id"] == model["attempt_id"] and a["kind"] == kind for a in refs) == 1
                         for kind in ("report_json", "report_html", "report_csv")):
            ready_version = version["version"]
            ready_artifact = model['id']
            break
    if requested_version is not None and ready_version is None:
        raise APIError('REPORT_VERSION_NOT_AVAILABLE', 404)
    if artifact_id is not None and artifact_id != ready_artifact:
        raise APIError('REPORT_ARTIFACT_MISMATCH', 422)
    error = run["error"] or (job["error"] if job else None)
    return {"run_id": run["id"], "root_run_id":run['root_run_id'], "parent_run_id":run['parent_run_id'],
            "dataset_id": dataset["id"], "project_id": project["id"],
            "app_id": project["app_id"], "name": project["name"], "created_at": run["created_at"],
            "status": run["status"], "kind": run["kind"], "progress": run["progress"], "error": error,
            "ready": run["status"] == "succeeded" and ready_version is not None,
            "report_version": ready_version, "report_artifact_id": ready_artifact,
            "synthetic": dataset["export_metadata"].get("synthetic", False),
            "attempt_number": job["attempt_number"] if job else None,
            "max_attempts": job["max_attempts"] if job else None,
            "can_retry": bool(job and run["kind"] == "baseline" and run["status"] == "failed"
                              and (error or {}).get("code") in RETRY_CODES and not refs and not versions)}


def branch_reports(service, run_id, limit=25, cursor=None):
    """Root-scoped published report identities only; never disclose report metrics or enqueue work."""
    params = {'run': run_id, 'limit': limit + 1}
    after = ''
    if cursor:
        try:
            stamp, identity, version = cursor.split('|')
            stamp = datetime.fromisoformat(stamp)
            if stamp.tzinfo is None or int(version) < 1:
                raise ValueError()
            params.update(stamp=stamp, identity=UUID(identity), version=int(version))
        except (ValueError, TypeError) as error:
            raise APIError('INVALID_BRANCH_CURSOR', 422) from error
        after = 'AND (r.created_at,r.id,v.version) < (:stamp,:identity,:version)'
    with service.engine.connect() as c:
        run = service.row(c, 'runs', run_id)
        params['root'] = run['root_run_id']
        rows = c.execute(text(f"""
            SELECT r.id AS run_id,r.parent_run_id,r.kind,r.created_at,
                   r.config->'windows_hours' AS windows_hours,
                   r.config->'segment' AS segment,
                   r.config->'thresholds' AS thresholds,
                   v.version AS report_version,a.id AS artifact_id
            FROM runs r JOIN report_versions v ON v.run_id=r.id
            JOIN artifacts a ON a.id=v.artifact_id AND a.run_id=r.id AND a.kind='report_json'
            WHERE r.root_run_id=:root AND r.status='succeeded'
            AND (SELECT count(*) FROM artifacts x WHERE x.run_id=r.id
                 AND x.attempt_id=a.attempt_id AND x.kind='report_json')=1
            AND (SELECT count(*) FROM artifacts x WHERE x.run_id=r.id
                 AND x.attempt_id=a.attempt_id AND x.kind='report_html')=1
            AND (SELECT count(*) FROM artifacts x WHERE x.run_id=r.id
                 AND x.attempt_id=a.attempt_id AND x.kind='report_csv')=1
            {after}
            ORDER BY r.created_at DESC,r.id DESC,v.version DESC LIMIT :limit
        """), params).mappings().all()
    items = [dict(row) for row in rows[:limit]]
    last = items[-1] if items else None
    next_cursor = (f"{last['created_at'].isoformat()}|{last['run_id']}|{last['report_version']}"
                   if len(rows) > limit else None)
    return {'root_run_id': run['root_run_id'], 'items': items, 'next_cursor': next_cursor}


def history(service, limit, cursor=None, dataset_id=None):
    runs, datasets, projects = [service.tables[name] for name in ("runs", "datasets", "projects")]
    query = select(runs.c.id.label("run_id"), runs.c.dataset_id, runs.c.status, runs.c.kind, runs.c.created_at,
                   projects.c.name, projects.c.app_id).select_from(runs.join(datasets).join(projects))
    if dataset_id:
        query = query.where(runs.c.dataset_id == dataset_id)
    if cursor:
        try:
            stamp, identity = cursor.split("|", 1)
            date = datetime.fromisoformat(stamp)
            if date.tzinfo is None:
                raise ValueError()
            identity = UUID(identity)
        except ValueError as error:
            raise APIError("INVALID_HISTORY_CURSOR", 422) from error
        query = query.where(tuple_(runs.c.created_at, runs.c.id) < tuple_(date, identity))
    with service.engine.connect() as c:
        if dataset_id:
            service.row(c, "datasets", dataset_id)
        rows = c.execute(query.order_by(runs.c.created_at.desc(), runs.c.id.desc()).limit(limit+1)).mappings().all()
    items = [dict(row) for row in rows[:limit]]
    next_cursor = f'{items[-1]["created_at"].isoformat()}|{items[-1]["run_id"]}' if len(rows)>limit else None
    return {"items": items, "next_cursor": next_cursor}


def retry_run(service, run_id, key):
    def action(c):
        # Same lock order as lease ownership: job first, then run. Never revive a published report.
        service.row(c, "runs", run_id)
        job = c.execute(text("SELECT * FROM jobs WHERE run_id=:id AND queue='compute' FOR UPDATE"), {"id": run_id}).mappings().one_or_none()
        run = service.row(c, "runs", run_id, True)
        code = (run["error"] or {}).get("code")
        if not job or run["kind"] != "baseline" or run["status"] != "failed" or job["status"] != "failed" or code not in RETRY_CODES:
            raise APIError("RUN_RETRY_NOT_ALLOWED")
        artifacts, reports = service.tables["artifacts"], service.tables["report_versions"]
        if c.execute(select(artifacts.c.id).where(artifacts.c.run_id == run_id).limit(1)).first() or c.execute(
                select(reports.c.id).where(reports.c.run_id == run_id).limit(1)).first():
            raise APIError("PUBLISHED_RUN_CANNOT_RETRY")
        c.execute(text("""UPDATE jobs SET status='queued',fence=fence+1,worker_id=NULL,lease_until=NULL,
            available_at=clock_timestamp(),cancel_requested=false,error=NULL,max_attempts=attempt_number+3
            WHERE id=:id"""), {"id": job["id"]})
        c.execute(text("""UPDATE runs SET status='queued',error=NULL,
            progress=jsonb_build_object('retry_requested',true,'previous_error',CAST(:code AS text)) WHERE id=:id"""),
                  {"id": run_id, "code": code})
        return {"run_id": str(run_id), "status": "queued"}
    return service.request(f"retry:{run_id}", key, {"run_id": str(run_id)}, action)

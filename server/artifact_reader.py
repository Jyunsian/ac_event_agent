"""Read committed run artifacts; never recompute capabilities in the HTTP layer."""
import json

from sqlalchemy import select

from server.storage import ObjectManifest
from server.uploads import APIError


def report_export_manifest(service, run_id, version, format):
    types = {"json": "application/json", "html": "text/html", "csv": "text/csv", "discovery": "application/json"}
    if format not in types or version < 1:
        raise APIError("REPORT_FORMAT_OR_VERSION_INVALID", 422)
    reports, artifacts = service.tables["report_versions"], service.tables["artifacts"]
    with service.engine.connect() as c:
        service.row(c, "runs", run_id)
        report = c.execute(select(reports).where(reports.c.run_id == run_id,
                                                reports.c.version == version)).mappings().one_or_none()
        if report is None:
            raise APIError("REPORT_NOT_READY")
        model = c.execute(select(artifacts).where(artifacts.c.id == report["artifact_id"],
                                                 artifacts.c.run_id == run_id)).mappings().one()
        if model["kind"] != "report_json":
            raise APIError("REPORT_VERSION_INVALID")
        rows = c.execute(select(artifacts).where(artifacts.c.run_id == run_id,
            artifacts.c.attempt_id == model["attempt_id"], artifacts.c.kind == ("discovery_json" if format=="discovery" else "report_"+format))).mappings().all()
        if len(rows) != 1:
            raise APIError("REPORT_EXPORT_AMBIGUOUS")
    artifact = rows[0]
    return ObjectManifest(artifact["object_key"], artifact["sha256"], artifact["size_bytes"], types[format])


def read_report_export(service, run_id, version, format):
    manifest = report_export_manifest(service, run_id, version, format)
    content = service.storage.get_bytes(manifest)
    if format == 'json':
        try:
            value=json.loads(content)
            if value.get('schema_version')=='4.0':
                from server.analysis.v4_report import validate_report
                validate_report(value,run_id=run_id)
            elif value.get('schema_version')=='3.0':
                from server.analysis.report_v3 import validate_report_v3_header
                validate_report_v3_header(value,run_id=run_id)
            else:
                from server.analysis.v2_contract import validate_report_header
                validate_report_header(value, run_id=run_id)
        except (ValueError, TypeError, KeyError) as error:
            raise APIError('REPORT_SCHEMA_INVALID') from error
    return content, manifest.content_type, manifest.sha256


def prepare_report_download(service, run_id, version, format):
    """Verify exports on disk before sending any bytes; retain the JSON index guard."""
    import shutil
    import tempfile
    from pathlib import Path
    if format == 'json':
        raise APIError('REPORT_FORMAT_OR_VERSION_INVALID', 422)
    manifest = report_export_manifest(service, run_id, version, format)
    work = tempfile.TemporaryDirectory(prefix='ac-report-download-')
    try:
        if shutil.disk_usage(work.name).free < manifest.size_bytes + 512*1024**2:
            raise APIError('REPORT_DOWNLOAD_DISK_UNAVAILABLE', 503)
        path = Path(work.name)/'export'
        service.storage.download_file(manifest, path)
        return work, path, manifest
    except BaseException:
        work.cleanup()
        raise


def read_quality_artifact(service, run_id, kind):
    if kind not in ("quality", "dataset_profile"):
        raise APIError("ARTIFACT_KIND_UNSUPPORTED", 422)
    table = service.tables["artifacts"]
    with service.engine.connect() as connection:
        service.row(connection, "runs", run_id)
        rows = connection.execute(select(table).where(
            table.c.run_id == run_id, table.c.kind == kind)).mappings().all()
    if not rows:
        raise APIError("ARTIFACT_NOT_READY")
    if len(rows) != 1:
        raise APIError("ARTIFACT_AMBIGUOUS")
    artifact = rows[0]
    data = service.storage.get_bytes(ObjectManifest(
        artifact["object_key"], artifact["sha256"], artifact["size_bytes"], "application/json"))
    try:
        content = json.loads(data)
        if (not isinstance(content, dict) or content.get("schema_version") not in ("1.0","3.0")
                or (content.get("schema_version")=="3.0" and content.get("analysis_version")!="3.0-casual-game")
                or not isinstance(content.get("capabilities"), dict)):
            raise ValueError("Invalid quality artifact")
    except (ValueError, UnicodeError) as error:
        raise APIError("ARTIFACT_INVALID") from error
    return {"run_id": run_id, "artifact_id": artifact["id"], "kind": kind,
            "sha256": artifact["sha256"], "content": content}

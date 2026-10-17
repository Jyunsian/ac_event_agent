"""Upload workflow; raw objects are immutable and only verified manifests may be sealed."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import insert, select, text, update

from server.db import IdempotencyConflict, Repository, fingerprint
from server.storage import StorageError


class APIError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


class UploadService:
    def __init__(self, engine, storage, max_upload_bytes=5*1024**3, part_size=8*1024**2):
        self.repo, self.storage = Repository(engine), storage
        self.engine, self.max_upload_bytes, self.part_size = engine, max_upload_bytes, part_size
        self.tables = self.repo.tables
        schema = json.loads((Path(__file__).resolve().parents[1]/"contracts/schema.json").read_text())
        self.validators = {name: Draft202012Validator({**schema, "$ref": f"#/$defs/{name}"},
                            format_checker=FormatChecker()) for name in ("config", "export")}

    def request(self, scope, key, payload, action):
        if not key or len(key) > 200:
            raise APIError("IDEMPOTENCY_KEY_REQUIRED", 422)
        digest = fingerprint(jsonable_encoder(payload))
        table = self.tables["api_requests"]
        with self.engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": scope+":"+key})
            old = c.execute(select(table).where(table.c.scope == scope, table.c.key == key)).mappings().one_or_none()
            if old:
                if old["request_hash"] != digest:
                    raise IdempotencyConflict()
                return old["response"]
            result = jsonable_encoder(action(c))
            c.execute(insert(table).values(scope=scope, key=key, request_hash=digest, response=result))
            return result

    def row(self, c, table_name, identity, lock=False):
        table = self.tables[table_name]
        query = select(table).where(table.c.id == identity)
        if lock:
            query = query.with_for_update()
        row = c.execute(query).mappings().one_or_none()
        if row is None:
            raise APIError("NOT_FOUND", 404)
        return row

    def editable(self, c, dataset_id):
        dataset = self.row(c, "datasets", dataset_id, True)
        if dataset["sealed_at"] is not None:
            raise APIError("DATASET_SEALED")
        return dataset

    def create_project(self, key, payload):
        return self.request("projects", key, payload, lambda c: dict(self.repo.create_project(c, **payload)))

    def create_dataset(self, key, project_id):
        def action(c):
            self.row(c, "projects", project_id)
            return dict(self.repo.create_dataset(c, project_id))
        return self.request("datasets", key, {"project_id": project_id}, action)

    def create_upload(self, key, dataset_id, payload):
        if payload["size_bytes"] > self.max_upload_bytes:
            raise APIError("UPLOAD_LIMIT_EXCEEDED", 413)
        count = math.ceil(payload["size_bytes"]/self.part_size)
        if count > 10000:
            raise APIError("UPLOAD_LIMIT_EXCEEDED", 413)
        def action(c):
            self.editable(c, dataset_id)
            identity = uuid4()
            table = self.tables["uploads"]
            c.execute(insert(table).values(id=identity, dataset_id=dataset_id,
                role=payload["role"], filename=payload["filename"], format=payload["format"],
                expected_size=payload["size_bytes"], expected_sha256=payload["sha256"],
                part_size=self.part_size, part_count=count,
                object_key=self.storage.new_key(f"source/{dataset_id}/{identity}", payload["format"])))
            return {"upload_id": str(identity)}
        # Commit identity before contacting S3 so a lost response can recover the same object key.
        result = self.request(f"uploads:{dataset_id}", key, payload, action)
        from uuid import UUID
        self.initialize_upload(UUID(result["upload_id"]))
        return result

    def initialize_upload(self, identity):
        with self.engine.begin() as c:
            upload = self.row(c, "uploads", identity, True)
            if upload["multipart_id"] is not None or upload["status"] != "uploading":
                return
            self.editable(c, upload["dataset_id"])
            # Recover an S3 initiation whose response/DB commit was lost; key belongs to this upload only.
            existing = self.storage.find_multipart(upload["object_key"])
            if len(existing) > 1:
                raise APIError("AMBIGUOUS_MULTIPART_STATE")
            multipart_id = existing[0] if existing else self.storage.start_multipart(upload["object_key"])
            c.execute(update(self.tables["uploads"]).where(self.tables["uploads"].c.id == identity)
                      .values(multipart_id=multipart_id))

    @staticmethod
    def match_file(upload, payload):
        if payload["size_bytes"] != upload["expected_size"] or payload["sha256"] != upload["expected_sha256"]:
            raise APIError("FILE_FINGERPRINT_MISMATCH")

    def resume(self, identity, payload, part_number=None):
        with self.engine.connect() as c:
            upload = self.row(c, "uploads", identity)
        self.match_file(upload, payload)
        self.initialize_upload(identity)
        with self.engine.connect() as c:
            upload = self.row(c, "uploads", identity)
        if upload["status"] == "completed":
            return {"status": "completed", "manifest": upload["verified_manifest"], "missing_parts": []}
        if upload["status"] != "uploading":
            raise APIError("UPLOAD_NOT_ACTIVE")
        try:
            parts = self.storage.list_parts(upload["object_key"], upload["multipart_id"])
        except StorageError as error:
            if error.code != "OBJECT_NOT_FOUND":
                raise
            self.storage.head(upload["object_key"])
            recovered = self.complete("resume-recovery", identity,
                                      {"size_bytes": payload["size_bytes"], "sha256": payload["sha256"]})
            return {**recovered, "missing_parts": []}
        expected = set(range(1, upload["part_count"]+1))
        missing = sorted(expected - {part["part_number"] for part in parts})
        result = {"status": "uploading", "part_size": upload["part_size"], "parts": parts, "missing_parts": missing}
        if part_number is not None:
            if part_number not in expected:
                raise APIError("INVALID_PART_NUMBER", 422)
            size = min(upload["part_size"], upload["expected_size"]-(part_number-1)*upload["part_size"])
            result["url"] = self.storage.presign_part(upload["object_key"], upload["multipart_id"], part_number, size)
        return result

    def complete(self, key, identity, payload):
        def action(c):
            upload = self.row(c, "uploads", identity, True)
            self.match_file(upload, payload)
            if upload["status"] == "completed":
                return {"status": "completed", "manifest": upload["verified_manifest"]}
            self.editable(c, upload["dataset_id"])
            if upload["status"] != "uploading" or not upload["multipart_id"]:
                raise APIError("UPLOAD_NOT_ACTIVE")
            try:
                self.storage.head(upload["object_key"])
            except StorageError as error:
                if error.code != "OBJECT_NOT_FOUND":
                    raise
                parts = self.storage.list_parts(upload["object_key"], upload["multipart_id"])
                if [part["part_number"] for part in parts] != list(range(1, upload["part_count"]+1)):
                    raise APIError("MISSING_PARTS")
                for part in parts:
                    expected = min(upload["part_size"], upload["expected_size"]-(part["part_number"]-1)*upload["part_size"])
                    if part["size_bytes"] != expected:
                        raise APIError("UPLOAD_SIZE_MISMATCH")
                self.storage.complete_multipart(upload["object_key"], upload["multipart_id"], parts)
            manifest = self.storage.verify_object(upload["object_key"], upload["expected_size"], upload["expected_sha256"]).to_dict()
            table = self.tables["uploads"]
            c.execute(update(table).where(table.c.id == identity).values(status="completed",
                      verified_manifest=manifest, completed_at=datetime.now(timezone.utc)))
            return {"status": "completed", "manifest": manifest}
        return self.request(f"complete:{identity}", key, payload, action)

    def save_mapping(self, key, identity, payload):
        if not self.validators["export"].is_valid(payload["export_metadata"]):
            raise APIError("INVALID_EXPORT_METADATA", 422)
        allowed = {"users": {"app_id","user_id","installed_at","platform","country","acquisition_source","campaign_id","app_version_at_install"},
                   "events": {"app_id","user_id","event_id","event_name","event_time","available_at","session_id","source_sequence","ad_format","revenue_usd","engaged_seconds","level_id","level_index","attempt_id","level_mode","difficulty","revive_used","booster_used","app_version"}}
        for role, mapping in payload["mapping"].items():
            if role not in allowed or not set(mapping).issubset(allowed[role]) or any(not name or len(name)>200 for name in mapping.values()):
                raise APIError("INVALID_MAPPING", 422)
        def action(c):
            self.editable(c, identity)
            c.execute(update(self.tables["datasets"]).where(self.tables["datasets"].c.id == identity).values(
                mapping=payload["mapping"], export_metadata=payload["export_metadata"]))
            return {"dataset_id": str(identity), "status": "mapping_saved"}
        return self.request(f"mapping:{identity}", key, payload, action)

    def baseline(self, key, identity, config, finding_ids=None):
        if not self.validators["config"].is_valid(config) or 'segment' in config:
            raise APIError("INVALID_ANALYSIS_CONFIG", 422)
        if config.get("analysis_version") == "3.0-casual-game":
            from server.analysis.v3_contract import V3ContractError, validate_config
            try:
                validate_config(config)
            except V3ContractError:
                raise APIError("INVALID_ANALYSIS_CONFIG", 422) from None
        if config.get("analysis_version") == "4.0-time-aware":
            from server.analysis.v4_contract import validate_config
            try:validate_config(config)
            except ValueError:raise APIError("INVALID_ANALYSIS_CONFIG",422) from None
        sources=None
        if finding_ids is not None:
            from server.finding_rechecks import resolve_sources
            sources=resolve_sources(self,identity,finding_ids,config)
        def action(c):
            dataset = self.editable(c, identity)
            uploads = c.execute(select(self.tables["uploads"]).where(
                self.tables["uploads"].c.dataset_id == identity).order_by(self.tables["uploads"].c.id)).mappings().all()
            if not uploads or any(upload["status"] != "completed" for upload in uploads):
                raise APIError("UPLOADS_INCOMPLETE")
            if sum(upload["role"] == "users" for upload in uploads) != 1 or not any(upload["role"] == "events" for upload in uploads):
                raise APIError("USERS_AND_EVENTS_REQUIRED", 422)
            if not self.validators["export"].is_valid(dataset["export_metadata"]):
                raise APIError("EXPORT_METADATA_REQUIRED", 422)
            required = {"users": {"app_id","user_id","installed_at","platform"},
                        "events": {"app_id","user_id","event_id","event_name","event_time"}}
            if any(not fields.issubset(dataset["mapping"].get(role, {})) for role, fields in required.items()):
                raise APIError("REQUIRED_MAPPING_MISSING", 422)
            manifest = [{**upload["verified_manifest"], "role": upload["role"], "format": upload["format"]} for upload in uploads]
            self.repo.seal_dataset(c, identity, manifest, dataset["mapping"], dataset["export_metadata"])
            calculation_version = config.get("analysis_version", "2.0")
            run = self.repo.create_run(c, identity, config, f"baseline:{identity}:{key}", calculation_version=calculation_version)
            if sources is not None:
                from server.finding_rechecks import save_recheck
                save_recheck(c,self,run['id'],sources)
            return {"run_id": str(run["id"]), "status": "queued"}
        return self.request(f"baseline:{identity}", key, config if sources is None else {'config':config,'finding_sources':sources}, action)

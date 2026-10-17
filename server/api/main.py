import os
import hmac
import threading
from typing import Annotated
from uuid import UUID

from fastapi import Body, Depends, FastAPI, Header, Request, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from server.db import IdempotencyConflict, database_engine
from server.storage import S3Storage, StorageError
from server.uploads import APIError, UploadService
from server.api.schemas import DatasetCreate, MappingSave, PartRequest, ProjectCreate, ResumeRequest, UploadCreate
from server.artifact_reader import read_quality_artifact, read_report_export, prepare_report_download
from server.candidate_reader import read_candidate_detail, read_candidate_page, read_candidate_search, read_candidate_revenue_series
from server.candidate_exports import read_candidate_export
from server.run_views import history, run_view, retry_run, branch_reports
from server.conversations import create_conversation, send_message, read_events
from server.conversations import cancel_turn, conversation_state
from server.conversations import retry_turn
from server.conversations import turn_context
from server.conversations import resolve_reference
from server.agent_queue import AgentQueue, AgentLeaseLost
from server.api.schemas import AgentClaimRequest, AgentOperation
from server.api.schemas import AgentJournalRequest
from server.agent_journal import journal
from server.agent_steps import steps
from server.api.schemas import AgentStepRequest
from server.api.schemas import MessageCreate
from server.api.schemas import ReadToolRequest
from server.read_tools import read_tool
from server.findings import findings_tool
from server.agent_status import agent_status
from server.validation_exposure import record_report_exposure
from server.branches import create_branch,branch_lineage,compute_tool
from server.exploration import exploration_tool

async def idempotency_conflict_handler(request, error):
    return JSONResponse(status_code=409, content={
        "error_code": error.code, "message": str(error), "retryable": False})

Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def create_app(engine=None, storage=None, max_upload_bytes=None, part_size=8*1024**2):
    app = FastAPI(title="AC Event Agent", version="0.1.0")
    app.add_exception_handler(IdempotencyConflict, idempotency_conflict_handler)
    app.state.upload_service = None
    resource_lock = threading.Lock()

    def internal_authorized(request):
        expected=os.environ.get('AGENT_INTERNAL_TOKEN','')
        supplied=request.headers.get('Authorization','')
        if not expected:raise APIError('INTERNAL_API_NOT_CONFIGURED',503)
        if not hmac.compare_digest(supplied.encode(),('Bearer '+expected).encode()):
            raise APIError('INTERNAL_API_UNAUTHORIZED',401)

    @app.exception_handler(AgentLeaseLost)
    async def lease_lost(request,error):
        return JSONResponse(status_code=409,content={'error_code':'AGENT_LEASE_LOST','retryable':False})

    @app.exception_handler(APIError)
    async def api_error(request, error):
        return JSONResponse(status_code=error.status, content={"error_code": error.code,
                            "message": error.code, "retryable": False})

    @app.exception_handler(StorageError)
    async def storage_error(request, error):
        code = 503 if error.retryable else (404 if error.code == "OBJECT_NOT_FOUND" else 409)
        return JSONResponse(status_code=code, content={"error_code": error.code,
                            "message": error.code, "retryable": error.retryable})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        return JSONResponse(status_code=503, content={"error_code": "DATABASE_UNAVAILABLE",
                            "message": "Database operation failed", "retryable": True})

    def service(request: Request):
        with resource_lock:
            if request.app.state.upload_service is None:
                if engine is None and not os.environ.get("DATABASE_URL"):
                    raise APIError("DATABASE_NOT_CONFIGURED", 503)
                request.app.state.upload_service = UploadService(
                    engine if engine is not None else database_engine(),
                    storage if storage is not None else S3Storage.from_environment(),
                    max_upload_bytes if max_upload_bytes is not None else int(os.environ.get("MAX_UPLOAD_BYTES", 5*1024**3)),
                    part_size)
        return request.app.state.upload_service

    @app.get("/api/health")
    def health():
        return {"service": "api", "status": "alive", "analysis_ready": False,
                "analysis_pipeline_available": True, "readiness_verified": False}

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectCreate, key: Key, svc=Depends(service)):
        return svc.create_project(key, body.model_dump())

    @app.post("/api/datasets", status_code=201)
    def create_dataset(body: DatasetCreate, key: Key, svc=Depends(service)):
        return svc.create_dataset(key, body.project_id)

    @app.get("/api/datasets/{dataset_id}")
    def get_dataset(dataset_id: UUID, svc=Depends(service)):
        with svc.engine.connect() as c:
            return dict(svc.row(c, "datasets", dataset_id))

    @app.post("/api/datasets/{dataset_id}/uploads", status_code=201)
    def create_upload(dataset_id: UUID, body: UploadCreate, key: Key, svc=Depends(service)):
        return svc.create_upload(key, dataset_id, body.model_dump())

    @app.get("/api/datasets/{dataset_id}/uploads")
    def list_uploads(dataset_id: UUID, svc=Depends(service)):
        with svc.engine.connect() as c:
            svc.row(c, "datasets", dataset_id)
            table = svc.tables["uploads"]
            # Browser resume needs file identity, not storage credentials or multipart IDs.
            columns = [table.c[name] for name in ("id", "role", "filename", "format", "expected_size",
                "expected_sha256", "part_size", "part_count", "status")]
            rows = c.execute(select(*columns).where(table.c.dataset_id == dataset_id).order_by(table.c.id)).mappings().all()
            return {"dataset_id": dataset_id, "uploads": [dict(row) for row in rows]}

    @app.post("/api/uploads/{upload_id}/resume")
    def resume_upload(upload_id: UUID, body: ResumeRequest, svc=Depends(service)):
        return svc.resume(upload_id, body.model_dump())

    @app.post("/api/uploads/{upload_id}/parts")
    def sign_part(upload_id: UUID, body: PartRequest, svc=Depends(service)):
        return svc.resume(upload_id, body.model_dump(), body.part_number)

    @app.post("/api/uploads/{upload_id}/complete")
    def complete_upload(upload_id: UUID, body: ResumeRequest, key: Key, svc=Depends(service)):
        return svc.complete(key, upload_id, body.model_dump())

    @app.put("/api/datasets/{dataset_id}/mapping")
    def mapping(dataset_id: UUID, body: MappingSave, key: Key, svc=Depends(service)):
        return svc.save_mapping(key, dataset_id, body.model_dump())

    @app.post("/api/datasets/{dataset_id}/baseline", status_code=202)
    def baseline(dataset_id: UUID, key: Key, config: dict = Body(...), svc=Depends(service)):
        return svc.baseline(key, dataset_id, config)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: UUID, svc=Depends(service)):
        view=run_view(svc,run_id)
        if view['ready']:record_report_exposure(svc,run_id,view['report_version'],'run_summary')
        with svc.engine.connect() as c:
            return dict(svc.row(c, "runs", run_id))

    @app.post('/api/datasets/{dataset_id}/finding-recheck',status_code=202)
    def finding_recheck(dataset_id: UUID,key: Key,body: dict=Body(...),svc=Depends(service)):
        if set(body)!={'config','finding_ids'} or not isinstance(body['finding_ids'],list):raise APIError('INVALID_RECHECK_REQUEST',422)
        return svc.baseline(key,dataset_id,body['config'],body['finding_ids'])

    @app.get('/api/datasets/{dataset_id}/recheck-sources')
    def recheck_sources(dataset_id: UUID,limit: int=Query(default=25,ge=1,le=100),
                        cursor: str | None=Query(default=None,max_length=180),svc=Depends(service)):
        from server.finding_rechecks import list_recheck_sources
        return list_recheck_sources(svc,dataset_id,limit,cursor)

    @app.get("/api/runs")
    def list_runs(limit: int = Query(default=50, ge=1, le=100), cursor: str | None = Query(default=None, max_length=150),
                  dataset_id: UUID | None = None, svc=Depends(service)):
        return history(svc, limit, cursor, dataset_id)

    @app.get("/api/runs/{run_id}/view")
    def get_run_view(run_id: UUID, version: int | None = Query(default=None, ge=1),
                     artifact: UUID | None = None, svc=Depends(service)):
        view=run_view(svc,run_id,version,artifact)
        if view['ready']:record_report_exposure(svc,run_id,view['report_version'],'run_summary')
        return view

    @app.get('/api/runs/{run_id}/branch-reports')
    def get_branch_reports(run_id: UUID, limit: int = Query(default=25, ge=1, le=100),
                           cursor: str | None = Query(default=None, max_length=180), svc=Depends(service)):
        return branch_reports(svc,run_id,limit,cursor)

    @app.post("/api/runs/{run_id}/retry", status_code=202)
    def retry(run_id: UUID, key: Key, svc=Depends(service)):
        return retry_run(svc, run_id, key)

    @app.get("/api/runs/{run_id}/quality")
    def get_quality(run_id: UUID, svc=Depends(service)):
        return read_quality_artifact(svc, run_id, "quality")

    @app.get("/api/runs/{run_id}/profile")
    def get_profile(run_id: UUID, svc=Depends(service)):
        return read_quality_artifact(svc, run_id, "dataset_profile")

    @app.get("/api/runs/{run_id}/reports/{version}/candidate-revenue-series")
    def get_candidate_revenue_series(run_id: UUID, version: int, svc=Depends(service)):
        result=read_candidate_revenue_series(svc,run_id,version)
        record_report_exposure(svc,run_id,version,'report_export')
        return result

    @app.get("/api/runs/{run_id}/reports/{version}/candidate-search")
    def get_candidate_search(run_id: UUID, version: int, page: int=1, svc=Depends(service)):
        result=read_candidate_search(svc,run_id,version,page)
        record_report_exposure(svc,run_id,version,'report_export')
        return result

    @app.get("/api/runs/{run_id}/reports/{version}/candidates")
    def get_candidate_page(run_id: UUID, version: int, page: int = 1,
                           window_hours: int | None = None, family: str | None = None,
                           ad_format: str | None = None, evidence_status: str | None = None,
                           role: str | None = None, category: str | None = None, sort: str = 'candidate_id',
                           descending: bool = False, svc=Depends(service)):
        result = read_candidate_page(svc, run_id, version, page=page, window_hours=window_hours,
            family=family, ad_format=ad_format, evidence_status=evidence_status, role=role, category=category,
            sort=sort, descending=descending)
        record_report_exposure(svc, run_id, version, 'report_export')
        return result

    @app.get("/api/runs/{run_id}/reports/{version}/candidate-exports/{format}")
    def get_candidate_export(run_id: UUID, version: int, format: str, scope: str = 'complete',
                             window_hours: int | None = None, family: str | None = None,
                             ad_format: str | None = None, evidence_status: str | None = None,
                             role: str | None = None, category: str | None = None, sort: str | None = None,
                             descending: bool | None = None, svc=Depends(service)):
        query={key:value for key,value in dict(window_hours=window_hours,family=family,ad_format=ad_format,
            evidence_status=evidence_status,role=role,category=category,sort=sort,descending=descending).items() if value is not None}
        data,mime,sha=read_candidate_export(svc,run_id,version,format,scope=scope,**query)
        record_report_exposure(svc,run_id,version,'report_export')
        return Response(data,media_type=mime,headers={'ETag':'"'+sha+'"',
            'Content-Disposition':f'attachment; filename="candidates-{scope}-{run_id}-v{version}.{format}"',
            'X-Content-Type-Options':'nosniff'})

    @app.get("/api/runs/{run_id}/reports/{version}/candidates/{candidate_id}")
    def get_candidate_detail(run_id: UUID, version: int, candidate_id: str, svc=Depends(service)):
        result = read_candidate_detail(svc, run_id, version, candidate_id)
        record_report_exposure(svc, run_id, version, 'report_export')
        return result

    @app.get("/api/runs/{run_id}/reports/{version}/{format}")
    def get_report(run_id: UUID, version: int, format: str, svc=Depends(service)):
        if format != 'json':
            work, path, manifest = prepare_report_download(svc, run_id, version, format)
            try:
                record_report_exposure(svc,run_id,version,'report_export')
            except BaseException:
                work.cleanup()
                raise
            async def chunks():
                try:
                    with path.open('rb') as source:
                        while chunk := source.read(64*1024):
                            yield chunk
                finally:
                    work.cleanup()
            return StreamingResponse(chunks(), media_type=manifest.content_type,
                background=BackgroundTask(work.cleanup), headers={
                    'Content-Length': str(manifest.size_bytes),
                    'Content-Disposition': f'attachment; filename="report-{run_id}-v{version}.{format}"',
                    'ETag': '"'+manifest.sha256+'"', 'X-Content-Type-Options': 'nosniff',
                    'Content-Security-Policy': "sandbox; default-src 'none'; style-src 'unsafe-inline'"})
        content, mime, checksum = read_report_export(svc, run_id, version, format)
        record_report_exposure(svc,run_id,version,'report_export')
        return Response(content, media_type=mime, headers={
            "Content-Disposition": f'attachment; filename="report-{run_id}-v{version}.{format}"',
            "ETag": '"'+checksum+'"', "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"})

    @app.post("/api/runs/{run_id}/conversations", status_code=201)
    def conversation_create(run_id: UUID, key: Key, svc=Depends(service)):
        return create_conversation(svc, run_id, key)

    @app.get('/api/runs/{run_id}/conversations')
    def conversations_list(run_id: UUID,svc=Depends(service)):
        with svc.engine.connect() as c:
            svc.row(c,'runs',run_id)
            table=svc.tables['conversations']
            rows=c.execute(select(table.c.id,table.c.baseline_run_id,table.c.created_at)
                .where(table.c.baseline_run_id==run_id).order_by(table.c.created_at.desc(),table.c.id).limit(100)).mappings().all()
            return {'conversations':[dict(row) for row in rows],'limit':100}

    @app.post("/api/conversations/{conversation_id}/messages", status_code=202)
    def message_create(conversation_id: UUID, body: MessageCreate, key: Key, svc=Depends(service)):
        return send_message(svc, conversation_id, key, body.model_dump())

    @app.get("/api/conversations/{conversation_id}/events")
    def conversation_events(conversation_id: UUID, after: int = Query(0, ge=0),
                            limit: int = Query(100, ge=1, le=200), svc=Depends(service)):
        return read_events(svc, conversation_id, after, limit)

    @app.post('/internal/tools/{name}')
    def readonly_tool(name: str, body: ReadToolRequest, request: Request, svc=Depends(service)):
        expected=os.environ.get('AGENT_INTERNAL_TOKEN','')
        supplied=request.headers.get('Authorization','')
        if not expected:
            raise APIError('INTERNAL_API_NOT_CONFIGURED',503)
        if not hmac.compare_digest(supplied.encode(),('Bearer '+expected).encode()):
            raise APIError('INTERNAL_API_UNAUTHORIZED',401)
        if name in ('rerun_analysis','analyze_segment','evaluate_analysis'):return compute_tool(svc,name,body.model_dump())
        if name in ('get_exploration_budget','finalize_candidates'):return exploration_tool(svc,name,body.model_dump())
        if name in ('load_app_findings','save_findings'):return findings_tool(svc,name,body.model_dump())
        return read_tool(svc,name,body.model_dump())

    @app.get('/api/agent/status')
    def get_agent_status():
        return agent_status()

    @app.post('/internal/analysis/branches',status_code=202)
    def analysis_branch(body: ReadToolRequest,request: Request,svc=Depends(service)):
        internal_authorized(request)
        return create_branch(svc,body.model_dump())

    @app.get('/api/runs/{run_id}/lineage')
    def get_branch_lineage(run_id: UUID,svc=Depends(service)):
        return branch_lineage(svc,run_id)

    @app.get('/api/runs/{run_id}/references/{artifact_id}')
    def get_reference(run_id: UUID,artifact_id: UUID,version: int=Query(ge=1),pointer: str=Query(max_length=100),svc=Depends(service)):
        return resolve_reference(svc,run_id,artifact_id,version,pointer)

    @app.get('/api/conversations/{conversation_id}')
    def get_conversation(conversation_id: UUID, svc=Depends(service)):
        return conversation_state(svc,conversation_id)

    @app.post('/api/turns/{turn_id}/cancel')
    def cancel_agent_turn(turn_id: UUID,key: Key,svc=Depends(service)):
        return cancel_turn(svc,turn_id,key)

    @app.post('/api/turns/{turn_id}/retry',status_code=202)
    def retry_agent_turn(turn_id: UUID,key: Key,svc=Depends(service)):
        return retry_turn(svc,turn_id,key)

    @app.post('/internal/agent/claim')
    def claim_agent(body: AgentClaimRequest,request: Request,svc=Depends(service)):
        internal_authorized(request)
        return {'claim':AgentQueue(svc.engine).claim(body.worker_id)}

    @app.post('/internal/agent/{operation}')
    def operate_agent(operation: str,body: AgentOperation,request: Request,svc=Depends(service)):
        internal_authorized(request)
        if operation not in ('context','heartbeat','finish','fail'):raise APIError('OPERATION_NOT_ALLOWED',422)
        with svc.engine.connect() as c:turn=svc.row(c,'agent_turns',body.turn_id)
        claim={'id':body.turn_id,'conversation_id':turn['conversation_id'],'worker_id':body.worker_id,'fence':body.fence}
        queue=AgentQueue(svc.engine)
        if operation=='context':return turn_context(svc,claim)
        if operation=='heartbeat':queue.heartbeat(claim)
        elif operation=='finish':queue.finish(claim,body.content)
        elif operation=='fail':queue.fail(claim,body.error_code)
        return {'status':'accepted'}

    @app.post('/internal/agent/journal/{operation}')
    def agent_journal(operation: str,body: AgentJournalRequest,request: Request,svc=Depends(service)):
        internal_authorized(request)
        if operation not in ('load','begin','complete'):raise APIError('OPERATION_NOT_ALLOWED',422)
        with svc.engine.connect() as c:turn=svc.row(c,'agent_turns',body.turn_id)
        claim={'id':body.turn_id,'conversation_id':turn['conversation_id'],'worker_id':body.worker_id,'fence':body.fence}
        return journal(svc,claim,operation,body.model_dump())

    @app.post('/internal/agent/steps/{operation}')
    def agent_steps(operation: str,body: AgentStepRequest,request: Request,svc=Depends(service)):
        internal_authorized(request)
        if operation not in ('init','load','start','complete'):raise APIError('OPERATION_NOT_ALLOWED',422)
        with svc.engine.connect() as c:turn=svc.row(c,'agent_turns',body.turn_id)
        claim={'id':body.turn_id,'conversation_id':turn['conversation_id'],'worker_id':body.worker_id,'fence':body.fence}
        return steps(svc,claim,operation,body.model_dump())

    return app


app = create_app()

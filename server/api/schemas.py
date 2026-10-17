from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(StrictModel):
    app_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    customer_label: str | None = Field(default=None, max_length=200)


class DatasetCreate(StrictModel):
    project_id: UUID


class ReportView(StrictModel):
    hours: Literal[24,48,72,96,120,144]
    cohort: Literal['observation','exploration','holdout']


class MessageCreate(StrictModel):
    content: str = Field(min_length=1, max_length=20000, pattern=r"\S")
    selected_run_id: UUID
    report_view: ReportView | None = None
    report_version: int | None = Field(default=None, ge=1, strict=True)
    selected_candidate_id: str | None = Field(default=None, min_length=1, max_length=256)


class ReadToolRequest(StrictModel):
    turn_id: UUID
    parent_run_id: UUID
    worker_id: str = Field(min_length=1, max_length=200)
    fence: int = Field(gt=0, strict=True)
    tool_call_id: str = Field(min_length=1, max_length=200)
    arguments: dict


class AgentClaimRequest(StrictModel):
    worker_id: str = Field(min_length=1,max_length=200)


class AgentOperation(AgentClaimRequest):
    turn_id: UUID
    fence: int = Field(gt=0,strict=True)
    content: str | None = Field(default=None,min_length=1,max_length=20000)
    error_code: str | None = Field(default=None,max_length=100)


class AgentJournalRequest(AgentClaimRequest):
    turn_id: UUID
    fence: int = Field(gt=0,strict=True)
    tool_call_id: str | None = Field(default=None,min_length=1,max_length=200)
    tool_name: str | None = Field(default=None,min_length=1,max_length=100)
    arguments: dict | None = None
    output: dict | None = None


class AgentStepRequest(AgentClaimRequest):
    turn_id: UUID
    fence: int = Field(gt=0,strict=True)
    config: dict | None = None
    request_id: str | None = Field(default=None,max_length=36)
    ordinal: int | None = Field(default=None,gt=0,le=20,strict=True)
    messages: list[dict] | None = None
    usage: dict | None = None
    finish_reason: str | None = Field(default=None,max_length=40)


class UploadCreate(StrictModel):
    role: Literal["users", "events"]
    filename: str = Field(min_length=1, max_length=255)
    format: Literal["csv", "parquet"]
    size_bytes: int = Field(gt=0, strict=True)
    sha256: SHA256


class ResumeRequest(StrictModel):
    size_bytes: int = Field(gt=0, strict=True)
    sha256: SHA256


class PartRequest(ResumeRequest):
    part_number: int = Field(ge=1, le=10000, strict=True)


class MappingSave(StrictModel):
    mapping: dict[str, dict[str, str]]
    export_metadata: dict

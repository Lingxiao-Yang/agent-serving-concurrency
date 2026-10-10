from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


class PolicyKind(StrEnum):
    STATIC_GLOBAL = "static_global"
    STATIC_STAGE = "static_stage"


class ModelKind(StrEnum):
    SCRIPTED = "scripted"
    VLLM = "vllm"


class RunStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    REJECTED = "rejected"


class Limits(BaseModel):
    n: int = Field(gt=0)
    k: int = Field(gt=0)
    m: int = Field(gt=0)
    max_n: int = Field(gt=0)
    max_k: int = Field(gt=0)
    max_m: int = Field(gt=0)

    @model_validator(mode="after")
    def within_maxima(self) -> Limits:
        if self.n > self.max_n or self.k > self.max_k or self.m > self.max_m:
            raise ValueError("initial limits must not exceed safety maxima")
        return self


class LimitUpdate(BaseModel):
    stage: Literal["n", "k", "m"]
    old_value: int = Field(gt=0)
    new_value: int = Field(gt=0)
    decision_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str


class TaskSpec(BaseModel):
    task_id: str
    family: Literal["sqlite", "data_analysis"]
    prompt: str
    fixture_id: str
    tool_name: Literal["sqlite_query", "data_analysis"]
    tool_arguments: dict[str, JsonValue]
    expected: JsonValue
    deadline_ms: int = Field(default=10_000, gt=0)


class RunRequest(BaseModel):
    request_id: str
    task_id: str
    deadline_ms: int | None = Field(default=None, gt=0)


class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, JsonValue]


class ToolExecuteRequest(BaseModel):
    run_id: str
    request_id: str
    trace_id: str
    task_id: str
    call: ToolCall
    timeout_ms: int = Field(gt=0)


class ToolExecutionResult(BaseModel):
    status: RunStatus
    value: JsonValue = None
    result_hash: str | None = None
    queue_wait_ms: float = 0.0
    service_ms: float = 0.0
    error: str | None = None


class RunResponse(BaseModel):
    run_id: str
    request_id: str
    trace_id: str
    task_id: str
    status: RunStatus
    answer: JsonValue = None
    result_hash: str | None = None
    action_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    trajectory: list[dict[str, JsonValue]] = Field(default_factory=list)
    error: str | None = None


class EventRecord(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str
    service: str
    request_id: str | None = None
    trace_id: str | None = None
    task_id: str | None = None
    stage: str
    event: str
    monotonic_ns: int
    wall_time: datetime
    queue_depth: int | None = None
    active: int | None = None
    limit: int | None = None
    queue_wait_ms: float | None = None
    duration_ms: float | None = None
    status: str | None = None
    tool_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    result_hash: str | None = None
    policy_decision_id: str | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)

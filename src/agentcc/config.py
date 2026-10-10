from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from agentcc.schemas import Limits, ModelKind, PolicyKind, TaskSpec


class QueueConfig(BaseModel):
    request: int = Field(default=128, ge=0)
    model: int = Field(default=128, ge=0)
    tool: int = Field(default=128, ge=0)


class TimeoutConfig(BaseModel):
    request_ms: int = Field(default=10_000, gt=0)
    model_ms: int = Field(default=5_000, gt=0)
    tool_ms: int = Field(default=5_000, gt=0)


class ModelConfig(BaseModel):
    kind: ModelKind = ModelKind.SCRIPTED
    delay_ms: float = Field(default=20.0, ge=0)
    base_url: str = "http://127.0.0.1:8002/v1"
    model: str = "Qwen/Qwen3-8B"
    revision: str = "unresolved"
    temperature: float = 0.0
    max_tokens: int = Field(default=256, gt=0)
    enable_thinking: bool = False


class ArrivalConfig(BaseModel):
    kind: Literal["steady", "poisson", "gamma", "burst"] = "steady"
    request_rate: float = Field(default=2.0, gt=0)
    burstiness: float = Field(default=1.0, gt=0)
    num_requests: int = Field(default=10, gt=0)
    burst_size: int = Field(default=5, gt=0)


class WorkloadConfig(BaseModel):
    catalog: Path = Path("workloads/tasks.yaml")
    mixture: dict[str, float] = Field(
        default_factory=lambda: {"sqlite": 0.5, "data_analysis": 0.5}
    )

    @model_validator(mode="after")
    def valid_mixture(self) -> WorkloadConfig:
        if not self.mixture or any(weight < 0 for weight in self.mixture.values()):
            raise ValueError("workload mixture must contain nonnegative weights")
        if sum(self.mixture.values()) <= 0:
            raise ValueError("at least one workload weight must be positive")
        return self


class ResourceConfig(BaseModel):
    tool_workers: int = Field(default=4, gt=0)
    tool_cpu_set: str | None = None
    within_tool_threads: int = Field(default=1, gt=0)


class ServiceConfig(BaseModel):
    agent_url: str = "http://127.0.0.1:8000"
    tool_url: str = "http://127.0.0.1:8001"


class TelemetryConfig(BaseModel):
    output_dir: Path = Path("results")


class RunConfig(BaseModel):
    run_id: str
    seed: int = 42
    policy: PolicyKind
    limits: Limits
    queues: QueueConfig = Field(default_factory=QueueConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    arrival: ArrivalConfig = Field(default_factory=ArrivalConfig)
    workload: WorkloadConfig = Field(default_factory=WorkloadConfig)
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    services: ServiceConfig = Field(default_factory=ServiceConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    max_actions: int = Field(default=4, gt=0)

    @model_validator(mode="after")
    def workers_cover_max_k(self) -> RunConfig:
        if self.resources.tool_workers < self.limits.max_k:
            raise ValueError("tool_workers must be at least max_k")
        return self

    def stable_hash(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @property
    def run_dir(self) -> Path:
        return self.telemetry.output_dir / self.run_id


def load_run_config(path: str | Path) -> RunConfig:
    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = RunConfig.model_validate(raw)
    root = config_path.parent.parent
    if not config.workload.catalog.is_absolute():
        config.workload.catalog = (root / config.workload.catalog).resolve()
    if not config.telemetry.output_dir.is_absolute():
        config.telemetry.output_dir = (root / config.telemetry.output_dir).resolve()
    config.services.agent_url = os.getenv("AGENTCC_AGENT_URL", config.services.agent_url)
    config.services.tool_url = os.getenv("AGENTCC_TOOL_URL", config.services.tool_url)
    return config


def load_tasks(path: str | Path) -> dict[str, TaskSpec]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    tasks = [TaskSpec.model_validate(item) for item in raw["tasks"]]
    if len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError("task IDs must be unique")
    return {task.task_id: task for task in tasks}

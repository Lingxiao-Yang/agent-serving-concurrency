from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from agentcc.admission import AdjustableFifoLimiter, LimiterQueueFull
from agentcc.admission.policies import policy_for
from agentcc.agent.backends import ModelBackend, create_model_backend
from agentcc.agent.graph import AgentState, build_agent_graph
from agentcc.config import RunConfig, load_tasks
from agentcc.schemas import RunRequest, RunResponse, RunStatus
from agentcc.telemetry.events import EventWriter
from agentcc.telemetry.metrics import ServiceMetrics
from agentcc.telemetry.tracing import configure_otel, tracer


class AgentLimitRequest(BaseModel):
    value: int = Field(gt=0)
    decision_id: str
    reason: str


def create_agent_app(
    config: RunConfig,
    *,
    writer: EventWriter | None = None,
    backend: ModelBackend | None = None,
    tool_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    tasks = load_tasks(config.workload.catalog)
    limits = policy_for(config).initial_limits()
    request_limiter = AdjustableFifoLimiter("n", limits.n, config.queues.request)
    model_limiter = AdjustableFifoLimiter("m", limits.m, config.queues.model)
    event_writer = writer or EventWriter(
        config.run_dir / "events" / "agent-service.jsonl", config.run_id, "agent-service"
    )
    model_backend = backend or create_model_backend(config.model)
    owned_client = tool_client is None
    client = tool_client or httpx.AsyncClient(base_url=config.services.tool_url)
    metrics = ServiceMetrics("agent-service")
    graph = build_agent_graph(config, model_backend, model_limiter, client, event_writer)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        event_writer.close()
        await model_backend.close()
        if owned_client:
            await client.aclose()

    app = FastAPI(title="agentcc agent service", version="0.1.0", lifespan=lifespan)
    app.state.request_limiter = request_limiter
    app.state.model_limiter = model_limiter
    app.state.graph = graph
    configure_otel(app, "agentcc-agent-service")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "run_id": config.run_id}

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        for stage, limiter in (("n", request_limiter), ("m", model_limiter)):
            snapshot = await limiter.snapshot()
            metrics.update_limiter(stage, snapshot.active, snapshot.limit, snapshot.queue_depth)
        return Response(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.put("/internal/limits/{stage}")
    async def update_local_limit(stage: str, update: AgentLimitRequest) -> dict[str, int]:
        choices = {
            "n": (request_limiter, limits.max_n),
            "m": (model_limiter, limits.max_m),
        }
        if stage not in choices:
            raise HTTPException(status_code=404, detail="unknown_local_limit")
        limiter, maximum = choices[stage]
        if update.value > maximum:
            raise HTTPException(status_code=422, detail=f"{stage} exceeds safety maximum")
        old = await limiter.snapshot()
        snapshot = await limiter.set_limit(update.value)
        event_writer.emit(
            stage=stage,
            event="limit_changed",
            snapshot=snapshot,
            policy_decision_id=update.decision_id,
            details={"old": old.limit, "new": update.value, "reason": update.reason},
        )
        return {stage: snapshot.limit}

    @app.post("/v1/runs", response_model=RunResponse)
    async def run_agent(request: RunRequest) -> RunResponse:
        task = tasks.get(request.task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="unknown_task")
        arrived_ns = time.monotonic_ns()
        deadline_ms = request.deadline_ms or task.deadline_ms
        trace_id = uuid.uuid4().hex
        event_writer.emit(
            stage="request",
            event="arrived",
            request_id=request.request_id,
            trace_id=trace_id,
            task_id=request.task_id,
        )
        event_writer.emit(
            stage="n",
            event="slot_enqueued",
            request_id=request.request_id,
            trace_id=trace_id,
            task_id=request.task_id,
            snapshot=await request_limiter.snapshot(),
        )
        try:
            admission = await asyncio.wait_for(
                request_limiter.acquire(), timeout=deadline_ms / 1000
            )
        except LimiterQueueFull as exc:
            metrics.terminal(RunStatus.REJECTED)
            event_writer.emit(
                stage="request",
                event="terminal",
                request_id=request.request_id,
                trace_id=trace_id,
                task_id=request.task_id,
                status=RunStatus.REJECTED,
                details={"error": "request_queue_full"},
            )
            raise HTTPException(status_code=429, detail="queue_full") from exc
        except TimeoutError:
            metrics.terminal(RunStatus.TIMEOUT)
            response = RunResponse(
                run_id=config.run_id,
                request_id=request.request_id,
                trace_id=trace_id,
                task_id=request.task_id,
                status=RunStatus.TIMEOUT,
                error="request_deadline_exceeded_in_admission",
            )
            event_writer.emit(
                stage="request",
                event="terminal",
                request_id=request.request_id,
                trace_id=trace_id,
                task_id=request.task_id,
                duration_ms=(time.monotonic_ns() - arrived_ns) / 1_000_000,
                status=RunStatus.TIMEOUT,
                details={"error": response.error},
            )
            return response

        event_writer.emit(
            stage="n",
            event="slot_acquired",
            request_id=request.request_id,
            trace_id=trace_id,
            task_id=request.task_id,
            queue_wait_ms=admission.wait_ms,
            snapshot=admission.snapshot,
        )
        started_ns = time.monotonic_ns()
        elapsed_s = (started_ns - arrived_ns) / 1_000_000_000
        remaining_s = max(0.0, (deadline_ms / 1000) - elapsed_s)
        try:
            initial: AgentState = {
                "request_id": request.request_id,
                "trace_id": trace_id,
                "task": task,
                "messages": [],
                "action_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "trajectory": [],
                "status": "running",
            }
            with tracer(__name__).start_as_current_span("agent.run"):
                state = await asyncio.wait_for(
                    graph.ainvoke(initial), timeout=remaining_s
                )
            status = RunStatus(state.get("status", RunStatus.ERROR))
            response = RunResponse(
                run_id=config.run_id,
                request_id=request.request_id,
                trace_id=trace_id,
                task_id=request.task_id,
                status=status,
                answer=state.get("answer"),
                result_hash=state.get("result_hash"),
                action_count=state.get("action_count", 0),
                input_tokens=state.get("input_tokens", 0),
                output_tokens=state.get("output_tokens", 0),
                trajectory=state.get("trajectory", []),
                error=state.get("error"),
            )
        except TimeoutError:
            status = RunStatus.TIMEOUT
            response = RunResponse(
                run_id=config.run_id,
                request_id=request.request_id,
                trace_id=trace_id,
                task_id=request.task_id,
                status=status,
                error="request_deadline_exceeded",
            )
        except Exception as exc:
            status = RunStatus.ERROR
            response = RunResponse(
                run_id=config.run_id,
                request_id=request.request_id,
                trace_id=trace_id,
                task_id=request.task_id,
                status=status,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            snapshot = await request_limiter.release()

        duration_ms = (time.monotonic_ns() - arrived_ns) / 1_000_000
        metrics.terminal(status)
        event_writer.emit(
            stage="n",
            event="slot_released",
            request_id=request.request_id,
            trace_id=trace_id,
            task_id=request.task_id,
            duration_ms=duration_ms,
            status=status,
            snapshot=snapshot,
        )
        event_writer.emit(
            stage="request",
            event="terminal",
            request_id=request.request_id,
            trace_id=trace_id,
            task_id=request.task_id,
            duration_ms=duration_ms,
            status=status,
            result_hash=response.result_hash,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            details={"error": response.error},
        )
        return response

    return app

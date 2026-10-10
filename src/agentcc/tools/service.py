from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from agentcc.admission import AdjustableFifoLimiter, LimiterQueueFull
from agentcc.config import RunConfig
from agentcc.schemas import RunStatus, ToolExecuteRequest, ToolExecutionResult
from agentcc.telemetry.events import EventWriter
from agentcc.telemetry.metrics import ServiceMetrics
from agentcc.telemetry.tracing import configure_otel, tracer
from agentcc.tools.workers import execute_tool


class ToolLimitRequest(BaseModel):
    k: int = Field(gt=0)
    decision_id: str
    reason: str


def create_tool_app(
    config: RunConfig,
    *,
    repository_root: Path,
    writer: EventWriter | None = None,
    executor: ProcessPoolExecutor | None = None,
) -> FastAPI:
    limits = config.limits
    initial_k = limits.max_k if config.policy.value == "static_global" else limits.k
    limiter = AdjustableFifoLimiter("k", initial_k, config.queues.tool)
    event_writer = writer or EventWriter(
        config.run_dir / "events" / "tool-service.jsonl", config.run_id, "tool-service"
    )
    metrics = ServiceMetrics("tool-service")
    owned_executor = executor is None
    pool = executor or ProcessPoolExecutor(max_workers=config.resources.tool_workers)
    cleanup_tasks: set[asyncio.Task[None]] = set()

    def forget_cleanup_task(done: asyncio.Future[None]) -> None:
        if isinstance(done, asyncio.Task):
            cleanup_tasks.discard(done)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        event_writer.close()
        if owned_executor:
            pool.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(title="agentcc tool service", version="0.1.0", lifespan=lifespan)
    app.state.limiter = limiter
    app.state.writer = event_writer
    app.state.executor = pool
    configure_otel(app, "agentcc-tool-service")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "run_id": config.run_id}

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        snapshot = await limiter.snapshot()
        metrics.update_limiter("k", snapshot.active, snapshot.limit, snapshot.queue_depth)
        return Response(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.put("/internal/limits/k")
    async def update_k(update: ToolLimitRequest) -> dict[str, int]:
        if update.k > limits.max_k:
            raise HTTPException(status_code=422, detail="k exceeds configured safety maximum")
        old = await limiter.snapshot()
        snapshot = await limiter.set_limit(update.k)
        event_writer.emit(
            stage="k",
            event="limit_changed",
            snapshot=snapshot,
            policy_decision_id=update.decision_id,
            details={"old": old.limit, "new": update.k, "reason": update.reason},
        )
        return {"k": snapshot.limit}

    @app.post("/internal/tools/execute", response_model=ToolExecutionResult)
    async def run_tool(request: ToolExecuteRequest) -> ToolExecutionResult:
        queued = await limiter.snapshot()
        event_writer.emit(
            stage="k",
            event="slot_enqueued",
            request_id=request.request_id,
            trace_id=request.trace_id,
            task_id=request.task_id,
            tool_name=request.call.name,
            snapshot=queued,
        )
        try:
            admission = await limiter.acquire()
        except LimiterQueueFull as exc:
            metrics.terminal(RunStatus.REJECTED)
            event_writer.emit(
                stage="k",
                event="queue_rejected",
                request_id=request.request_id,
                trace_id=request.trace_id,
                task_id=request.task_id,
                tool_name=request.call.name,
                status=RunStatus.REJECTED,
                snapshot=await limiter.snapshot(),
            )
            raise HTTPException(status_code=429, detail="queue_full") from exc

        metrics.update_limiter(
            "k", admission.snapshot.active, admission.snapshot.limit, admission.snapshot.queue_depth
        )
        event_writer.emit(
            stage="k",
            event="slot_acquired",
            request_id=request.request_id,
            trace_id=request.trace_id,
            task_id=request.task_id,
            tool_name=request.call.name,
            queue_wait_ms=admission.wait_ms,
            snapshot=admission.snapshot,
        )
        started_ns = time.monotonic_ns()
        status = RunStatus.SUCCESS
        worker_future: asyncio.Future[dict[str, Any]] | None = None

        async def release_and_record(
            terminal_status: RunStatus, result: ToolExecutionResult
        ) -> None:
            snapshot = await limiter.release()
            metrics.update_limiter("k", snapshot.active, snapshot.limit, snapshot.queue_depth)
            event_writer.emit(
                stage="k",
                event="slot_released",
                request_id=request.request_id,
                trace_id=request.trace_id,
                task_id=request.task_id,
                tool_name=request.call.name,
                duration_ms=(time.monotonic_ns() - started_ns) / 1_000_000,
                status=terminal_status,
                result_hash=result.result_hash,
                snapshot=snapshot,
            )

        async def release_after_worker(
            future: asyncio.Future[dict[str, Any]],
            terminal_status: RunStatus,
            result: ToolExecutionResult,
        ) -> None:
            try:
                await asyncio.shield(future)
            except Exception:
                pass
            await release_and_record(terminal_status, result)

        try:
            loop = asyncio.get_running_loop()
            with tracer(__name__).start_as_current_span(f"tool.{request.call.name}"):
                worker_future = loop.run_in_executor(
                    pool,
                    execute_tool,
                    request.call.name,
                    request.call.arguments,
                    str(repository_root),
                )
                result = await asyncio.wait_for(
                    asyncio.shield(worker_future), timeout=request.timeout_ms / 1000
                )
            service_ms = (time.monotonic_ns() - started_ns) / 1_000_000
            response = ToolExecutionResult(
                status=RunStatus.SUCCESS,
                value=result["value"],
                result_hash=result["result_hash"],
                queue_wait_ms=admission.wait_ms,
                service_ms=service_ms,
            )
        except TimeoutError:
            status = RunStatus.TIMEOUT
            response = ToolExecutionResult(
                status=status,
                queue_wait_ms=admission.wait_ms,
                service_ms=(time.monotonic_ns() - started_ns) / 1_000_000,
                error="tool_timeout",
            )
            assert worker_future is not None
            cleanup = asyncio.create_task(
                release_after_worker(worker_future, status, response)
            )
            cleanup_tasks.add(cleanup)
            cleanup.add_done_callback(forget_cleanup_task)
        except asyncio.CancelledError:
            status = RunStatus.ERROR
            response = ToolExecutionResult(
                status=status,
                queue_wait_ms=admission.wait_ms,
                service_ms=(time.monotonic_ns() - started_ns) / 1_000_000,
                error="caller_cancelled",
            )
            assert worker_future is not None
            cleanup = asyncio.create_task(
                release_after_worker(worker_future, status, response)
            )
            cleanup_tasks.add(cleanup)
            cleanup.add_done_callback(forget_cleanup_task)
            raise
        except Exception as exc:  # trusted worker errors are part of the benchmark result
            status = RunStatus.ERROR
            response = ToolExecutionResult(
                status=status,
                queue_wait_ms=admission.wait_ms,
                service_ms=(time.monotonic_ns() - started_ns) / 1_000_000,
                error=f"{type(exc).__name__}: {exc}",
            )

        metrics.terminal(status)
        if status != RunStatus.TIMEOUT:
            await release_and_record(status, response)
        return response

    return app

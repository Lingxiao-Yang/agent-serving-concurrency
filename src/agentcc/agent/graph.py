from __future__ import annotations

import asyncio
import time
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from agentcc.admission import AdjustableFifoLimiter, LimiterQueueFull
from agentcc.agent.backends import ModelBackend, ModelDecision
from agentcc.config import RunConfig
from agentcc.schemas import JsonValue, RunStatus, TaskSpec, ToolExecuteRequest
from agentcc.telemetry.events import EventWriter
from agentcc.telemetry.tracing import inject_trace_headers, tracer


class AgentState(TypedDict, total=False):
    request_id: str
    trace_id: str
    task: TaskSpec
    messages: list[dict[str, Any]]
    decision: ModelDecision
    last_tool_result: JsonValue
    result_hash: str | None
    action_count: int
    input_tokens: int
    output_tokens: int
    trajectory: list[dict[str, JsonValue]]
    answer: JsonValue
    status: str
    error: str | None


def build_agent_graph(
    config: RunConfig,
    backend: ModelBackend,
    model_limiter: AdjustableFifoLimiter,
    tool_client: httpx.AsyncClient,
    writer: EventWriter,
) -> Any:
    async def model_node(state: AgentState) -> dict[str, Any]:
        task = state["task"]
        request_id = state["request_id"]
        trace_id = state["trace_id"]
        writer.emit(
            stage="m",
            event="slot_enqueued",
            request_id=request_id,
            trace_id=trace_id,
            task_id=task.task_id,
            snapshot=await model_limiter.snapshot(),
        )
        try:
            admission = await model_limiter.acquire()
        except LimiterQueueFull:
            return {"status": RunStatus.REJECTED, "error": "model_queue_full"}
        writer.emit(
            stage="m",
            event="slot_acquired",
            request_id=request_id,
            trace_id=trace_id,
            task_id=task.task_id,
            queue_wait_ms=admission.wait_ms,
            snapshot=admission.snapshot,
        )
        started_ns = time.monotonic_ns()
        try:
            with tracer(__name__).start_as_current_span("agent.model"):
                decision = await asyncio.wait_for(
                    backend.decide(
                        task,
                        state.get("messages", []),
                        state.get("last_tool_result"),
                        state.get("action_count", 0),
                    ),
                    timeout=config.timeouts.model_ms / 1000,
                )
        except TimeoutError:
            decision = ModelDecision(kind="error", error="model_timeout")
        except Exception as exc:
            decision = ModelDecision(kind="error", error=f"{type(exc).__name__}: {exc}")
        finally:
            snapshot = await model_limiter.release()

        duration_ms = (time.monotonic_ns() - started_ns) / 1_000_000
        writer.emit(
            stage="m",
            event="slot_released",
            request_id=request_id,
            trace_id=trace_id,
            task_id=task.task_id,
            duration_ms=duration_ms,
            status=decision.kind,
            input_tokens=decision.input_tokens,
            output_tokens=decision.output_tokens,
            snapshot=snapshot,
        )
        action_count = state.get("action_count", 0)
        result: dict[str, Any] = {
            "decision": decision,
            "messages": decision.messages or state.get("messages", []),
            "input_tokens": state.get("input_tokens", 0) + decision.input_tokens,
            "output_tokens": state.get("output_tokens", 0) + decision.output_tokens,
        }
        if decision.kind == "tool":
            if action_count >= config.max_actions:
                result.update(status=RunStatus.ERROR, error="max_actions_exceeded")
            else:
                result["action_count"] = action_count + 1
        elif decision.kind == "final":
            result.update(status=RunStatus.SUCCESS, answer=decision.answer)
        else:
            result.update(status=RunStatus.ERROR, error=decision.error or "model_error")
        return result

    async def tool_node(state: AgentState) -> dict[str, Any]:
        decision = state["decision"]
        call = decision.tool_call
        if call is None:
            return {"status": RunStatus.ERROR, "error": "missing_tool_call"}
        task = state["task"]
        if call.name != task.tool_name:
            return {"status": RunStatus.ERROR, "error": f"unknown_or_disallowed_tool: {call.name}"}
        request = ToolExecuteRequest(
            run_id=config.run_id,
            request_id=state["request_id"],
            trace_id=state["trace_id"],
            task_id=task.task_id,
            call=call,
            timeout_ms=config.timeouts.tool_ms,
        )
        headers: dict[str, str] = {}
        inject_trace_headers(headers)
        try:
            with tracer(__name__).start_as_current_span("agent.tool_http"):
                response = await tool_client.post(
                    "/internal/tools/execute",
                    json=request.model_dump(mode="json"),
                    headers=headers,
                    timeout=(config.timeouts.tool_ms / 1000) + 1,
                )
            if response.status_code == 429:
                return {"status": RunStatus.REJECTED, "error": "tool_queue_full"}
            response.raise_for_status()
            result = response.json()
        except httpx.TimeoutException:
            return {"status": RunStatus.TIMEOUT, "error": "tool_http_timeout"}
        except httpx.HTTPError as exc:
            return {"status": RunStatus.ERROR, "error": f"tool_http_error: {exc}"}

        if result["status"] != RunStatus.SUCCESS:
            return {"status": result["status"], "error": result.get("error")}
        trajectory = list(state.get("trajectory", []))
        trajectory.append(
            {
                "tool": call.name,
                "call_id": call.call_id,
                "arguments": call.arguments,
                "result_hash": result["result_hash"],
            }
        )
        messages = list(state.get("messages", []))
        if messages:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "content": result["value"],
                }
            )
        return {
            "last_tool_result": result["value"],
            "result_hash": result["result_hash"],
            "trajectory": trajectory,
            "messages": messages,
            "status": "running",
        }

    def after_model(state: AgentState) -> str:
        if state.get("status") in {
            RunStatus.SUCCESS,
            RunStatus.ERROR,
            RunStatus.REJECTED,
            RunStatus.TIMEOUT,
        }:
            return END
        return "tool"

    def after_tool(state: AgentState) -> str:
        return "model" if state.get("status") == "running" else END

    builder = StateGraph(AgentState)
    builder.add_node("model", model_node)
    builder.add_node("tool", tool_node)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", after_model)
    builder.add_conditional_edges("tool", after_tool)
    return builder.compile()

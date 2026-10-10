from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from agentcc.agent.backends import ModelBackend, ModelDecision, ScriptedModelBackend
from agentcc.agent.service import create_agent_app
from agentcc.config import load_run_config
from agentcc.schemas import TaskSpec, ToolCall
from agentcc.telemetry.events import EventWriter
from agentcc.telemetry.validation import validate_events
from agentcc.tools.service import create_tool_app

ROOT = Path(__file__).resolve().parents[1]


class DisallowedToolBackend(ModelBackend):
    async def decide(
        self,
        task: TaskSpec,
        messages: list[dict[str, object]],
        last_tool_result: object,
        action_count: int,
    ) -> ModelDecision:
        del task, messages, last_tool_result, action_count
        return ModelDecision(
            kind="tool",
            tool_call=ToolCall(call_id="bad", name="shell", arguments={}),
        )


async def _apps(
    tmp_path: Path, backend: ModelBackend | None = None
) -> tuple[httpx.AsyncClient, EventWriter, EventWriter, ThreadPoolExecutor]:
    config = load_run_config(ROOT / "configs/cpu_smoke.yaml")
    config.telemetry.output_dir = tmp_path
    tool_writer = EventWriter(tmp_path / "events/tool.jsonl", config.run_id, "tool-service")
    agent_writer = EventWriter(tmp_path / "events/agent.jsonl", config.run_id, "agent-service")
    executor = ThreadPoolExecutor(max_workers=4)
    tool_app = create_tool_app(
        config, repository_root=ROOT, writer=tool_writer, executor=executor  # type: ignore[arg-type]
    )
    tool_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=tool_app), base_url="http://tool"
    )
    agent_app = create_agent_app(
        config,
        writer=agent_writer,
        backend=backend or ScriptedModelBackend(0),
        tool_client=tool_client,
    )
    agent_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent_app), base_url="http://agent"
    )
    return agent_client, agent_writer, tool_writer, executor


@pytest.mark.asyncio
async def test_end_to_end_both_workloads_and_trace_invariants(tmp_path: Path) -> None:
    client, agent_writer, tool_writer, executor = await _apps(tmp_path)
    try:
        responses = []
        for index, task_id in enumerate(("sqlite-region-sales", "analysis-region-mean")):
            response = await client.post(
                "/v1/runs", json={"request_id": f"request-{index}", "task_id": task_id}
            )
            assert response.status_code == 200
            responses.append(response.json())
        assert [item["status"] for item in responses] == ["success", "success"]
        assert responses[0]["answer"] == [["East", 250.0], ["West", 125.0]]
        assert responses[1]["answer"] == {"north": 15.0, "south": 15.0}
    finally:
        await client.aclose()
        agent_writer.close()
        tool_writer.close()
        executor.shutdown(wait=True)
    assert validate_events(tmp_path / "events") == []


@pytest.mark.asyncio
async def test_disallowed_tool_is_reported_without_execution(tmp_path: Path) -> None:
    client, agent_writer, tool_writer, executor = await _apps(tmp_path, DisallowedToolBackend())
    try:
        response = await client.post(
            "/v1/runs", json={"request_id": "bad-tool", "task_id": "sqlite-region-sales"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert "disallowed_tool" in body["error"]
    finally:
        await client.aclose()
        agent_writer.close()
        tool_writer.close()
        executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_model_timeout_releases_request_slot(tmp_path: Path) -> None:
    config = load_run_config(ROOT / "configs/cpu_smoke.yaml")
    config.telemetry.output_dir = tmp_path
    config.timeouts.model_ms = 1
    writer = EventWriter(tmp_path / "events/agent.jsonl", config.run_id, "agent-service")
    app = create_agent_app(config, writer=writer, backend=ScriptedModelBackend(50))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent")
    try:
        response = await client.post(
            "/v1/runs", json={"request_id": "timeout", "task_id": "sqlite-region-sales"}
        )
        assert response.json()["status"] == "error"
        assert response.json()["error"] == "model_timeout"
        assert (await app.state.request_limiter.snapshot()).active == 0
        assert (await app.state.model_limiter.snapshot()).active == 0
    finally:
        await client.aclose()
        writer.close()

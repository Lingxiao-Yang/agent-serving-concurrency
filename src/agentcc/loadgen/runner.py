from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any

import httpx

from agentcc.config import RunConfig, load_tasks
from agentcc.loadgen.arrivals import arrival_offsets
from agentcc.schemas import JsonValue, RunStatus, TaskSpec
from agentcc.telemetry.manifest import write_manifest
from agentcc.tools.workers import canonical_hash


def answers_equal(actual: JsonValue, expected: JsonValue) -> bool:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return abs(float(actual) - float(expected)) <= 1e-9
    if isinstance(actual, dict) and isinstance(expected, dict) and actual.keys() == expected.keys():
        return all(answers_equal(actual[key], expected[key]) for key in actual)
    if isinstance(actual, list) and isinstance(expected, list) and len(actual) == len(expected):
        return all(answers_equal(left, right) for left, right in zip(actual, expected, strict=True))
    return actual == expected


def _weighted_tasks(config: RunConfig, tasks: dict[str, TaskSpec]) -> list[TaskSpec]:
    families: dict[str, list[TaskSpec]] = {}
    for task in tasks.values():
        families.setdefault(task.family, []).append(task)
    selected: list[TaskSpec] = []
    weights: list[float] = []
    for family, weight in config.workload.mixture.items():
        for task in sorted(families.get(family, []), key=lambda item: item.task_id):
            selected.append(task)
            weights.append(weight / max(1, len(families[family])))
    if not selected:
        raise ValueError("workload mixture selects no tasks")
    rng = random.Random(config.seed)
    return rng.choices(selected, weights=weights, k=config.arrival.num_requests)


async def run_load(config: RunConfig, *, repository_root: Path) -> Path:
    tasks = load_tasks(config.workload.catalog)
    chosen = _weighted_tasks(config, tasks)
    offsets = arrival_offsets(config.arrival, config.seed)
    config.run_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(config, repository_root)
    output = config.run_dir / "requests.jsonl"
    output.write_text("", encoding="utf-8")
    run_start = time.perf_counter()
    write_lock = asyncio.Lock()

    async with httpx.AsyncClient(base_url=config.services.agent_url) as client:
        async def submit(index: int, offset: float, task: TaskSpec) -> dict[str, Any]:
            target = run_start + offset
            await asyncio.sleep(max(0.0, target - time.perf_counter()))
            scheduled_ns = time.perf_counter_ns()
            request_id = f"{config.run_id}-{index:06d}"
            try:
                response = await client.post(
                    "/v1/runs",
                    json={
                        "request_id": request_id,
                        "task_id": task.task_id,
                        "deadline_ms": task.deadline_ms,
                    },
                    timeout=(task.deadline_ms / 1000) + 2,
                )
                completed_ns = time.perf_counter_ns()
                if response.status_code == 429:
                    body: dict[str, Any] = {
                        "status": RunStatus.REJECTED,
                        "error": "request_queue_full",
                    }
                else:
                    response.raise_for_status()
                    body = response.json()
            except httpx.TimeoutException:
                completed_ns = time.perf_counter_ns()
                body = {"status": RunStatus.TIMEOUT, "error": "client_timeout"}
            except httpx.HTTPError as exc:
                completed_ns = time.perf_counter_ns()
                body = {"status": RunStatus.ERROR, "error": f"client_http_error: {exc}"}

            actual = body.get("answer")
            correct = body.get("status") == RunStatus.SUCCESS and answers_equal(
                actual, task.expected
            )
            record = {
                "schema_version": 1,
                "run_id": config.run_id,
                "request_id": request_id,
                "task_id": task.task_id,
                "family": task.family,
                "scheduled_offset_s": offset,
                "scheduled_ns": scheduled_ns,
                "completed_ns": completed_ns,
                "schedule_relative_latency_ms": (completed_ns - scheduled_ns) / 1_000_000,
                "status": str(body.get("status")),
                "correct": correct,
                "expected_hash": canonical_hash(task.expected),
                "actual_hash": canonical_hash(actual) if actual is not None else None,
                "response": body,
            }
            async with write_lock:
                with output.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            return record

        scheduled = enumerate(zip(offsets, chosen, strict=True))
        records = await asyncio.gather(
            *(submit(index, offset, task) for index, (offset, task) in scheduled)
        )

    summary = {
        "run_id": config.run_id,
        "requests": len(records),
        "successful": sum(item["status"] == RunStatus.SUCCESS for item in records),
        "correct": sum(item["correct"] for item in records),
        "rejected": sum(item["status"] == RunStatus.REJECTED for item in records),
        "timed_out": sum(item["status"] == RunStatus.TIMEOUT for item in records),
    }
    (config.run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return output

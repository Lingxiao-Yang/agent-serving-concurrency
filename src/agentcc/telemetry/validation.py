from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def read_events(path: Path) -> Iterable[dict[str, Any]]:
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    for file in files:
        with file.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON at {file}:{line_number}") from exc


def validate_events(path: Path) -> list[str]:
    errors: list[str] = []
    slot_counts: Counter[tuple[str, str, str]] = Counter()
    terminals: Counter[tuple[str, str]] = Counter()
    last_monotonic: dict[str, int] = defaultdict(int)
    grandfathered_active: dict[tuple[str, str], int] = {}
    for event in read_events(path):
        service = event["service"]
        timestamp = int(event["monotonic_ns"])
        if timestamp < last_monotonic[service]:
            errors.append(f"{service}: non-monotonic event timestamps")
        last_monotonic[service] = timestamp
        active = event.get("active")
        limit = event.get("limit")
        stage_key = (service, event["stage"])
        if active is not None and limit is not None and active > limit:
            if event["event"] == "limit_changed":
                grandfathered_active[stage_key] = active
            elif active <= grandfathered_active.get(stage_key, -1):
                grandfathered_active[stage_key] = active
            else:
                errors.append(
                    f"{service}/{event['stage']}: active {active} exceeds limit {limit}"
                )
        elif active is not None and limit is not None:
            grandfathered_active.pop(stage_key, None)
        wait = event.get("queue_wait_ms")
        if wait is not None and wait < 0:
            errors.append(f"{service}/{event['stage']}: negative queue wait")
        request_id = event.get("request_id")
        if request_id and event["event"] in {"slot_acquired", "slot_released"}:
            slot_key = (service, event["stage"], request_id)
            slot_counts[slot_key] += 1 if event["event"] == "slot_acquired" else -1
        if request_id and event["stage"] == "request" and event["event"] == "terminal":
            terminals[(service, request_id)] += 1

    for slot_key, balance in slot_counts.items():
        if balance != 0:
            errors.append(f"{slot_key}: unpaired slot events (balance {balance})")
    for terminal_key, count in terminals.items():
        if count != 1:
            errors.append(f"{terminal_key}: expected one terminal event, found {count}")
    return errors

from __future__ import annotations

import json
from pathlib import Path

from agentcc.telemetry.validation import validate_events


def test_validator_detects_oversubscription_and_unpaired_slots(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    rows = [
        {
            "service": "agent",
            "stage": "n",
            "event": "slot_acquired",
            "request_id": "r1",
            "monotonic_ns": 1,
            "active": 2,
            "limit": 1,
        },
        {
            "service": "agent",
            "stage": "request",
            "event": "terminal",
            "request_id": "r1",
            "monotonic_ns": 2,
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    errors = validate_events(path)
    assert any("exceeds" in error for error in errors)
    assert any("unpaired" in error for error in errors)

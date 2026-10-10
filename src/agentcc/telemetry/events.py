from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentcc.admission.limiter import LimiterSnapshot
from agentcc.schemas import EventRecord, JsonValue


class EventWriter:
    """Process-local, line-buffered writer for authoritative benchmark events."""

    def __init__(self, path: Path, run_id: str, service: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.run_id = run_id
        self.service = service
        # A run ID denotes one reproducible execution. Re-running the same ID
        # replaces its process-local event stream instead of silently mixing runs.
        self._file = path.open("w", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()

    def emit(
        self,
        *,
        stage: str,
        event: str,
        request_id: str | None = None,
        trace_id: str | None = None,
        task_id: str | None = None,
        snapshot: LimiterSnapshot | None = None,
        details: dict[str, JsonValue] | None = None,
        **fields: Any,
    ) -> EventRecord:
        record = EventRecord(
            run_id=self.run_id,
            service=self.service,
            request_id=request_id,
            trace_id=trace_id,
            task_id=task_id,
            stage=stage,
            event=event,
            monotonic_ns=time.monotonic_ns(),
            wall_time=datetime.now(UTC),
            queue_depth=snapshot.queue_depth if snapshot else None,
            active=snapshot.active if snapshot else None,
            limit=snapshot.limit if snapshot else None,
            details=details or {},
            **fields,
        )
        line = json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        with self._lock:
            self._file.write(line + "\n")
        return record

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()


class NullEventWriter:
    run_id = "null"
    service = "null"

    def emit(self, **_: Any) -> None:
        return None

    def close(self) -> None:
        return None

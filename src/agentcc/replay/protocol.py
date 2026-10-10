from __future__ import annotations

from typing import Protocol

from agentcc.schemas import JsonValue, TaskSpec


class TrajectoryReplay(Protocol):
    async def replay(self, task: TaskSpec) -> JsonValue:
        """Replay a recorded trajectory, failing visibly on divergence."""
        ...

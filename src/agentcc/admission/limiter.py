from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


class LimiterQueueFull(RuntimeError):
    """Raised when an admission queue has reached its configured capacity."""


@dataclass(frozen=True, slots=True)
class LimiterSnapshot:
    name: str
    limit: int
    active: int
    queue_depth: int


@dataclass(frozen=True, slots=True)
class Admission:
    wait_ms: float
    snapshot: LimiterSnapshot


@dataclass(slots=True)
class _Waiter:
    future: asyncio.Future[None]
    enqueued_ns: int
    granted: bool = False


class AdjustableFifoLimiter:
    """A cancellation-safe FIFO concurrency gate with a runtime-adjustable limit."""

    def __init__(self, name: str, limit: int, queue_capacity: int) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if queue_capacity < 0:
            raise ValueError("queue_capacity must be nonnegative")
        self.name = name
        self._limit = limit
        self._queue_capacity = queue_capacity
        self._active = 0
        self._waiters: deque[_Waiter] = deque()
        self._condition = asyncio.Condition()

    async def snapshot(self) -> LimiterSnapshot:
        async with self._condition:
            return self._snapshot_locked()

    async def acquire(self) -> Admission:
        started_ns = time.monotonic_ns()
        waiter: _Waiter | None = None
        async with self._condition:
            if self._active < self._limit and not self._waiters:
                self._active += 1
                return Admission(0.0, self._snapshot_locked())
            if len(self._waiters) >= self._queue_capacity:
                raise LimiterQueueFull(f"{self.name} queue is full")
            loop = asyncio.get_running_loop()
            waiter = _Waiter(loop.create_future(), started_ns)
            self._waiters.append(waiter)

        try:
            await asyncio.shield(waiter.future)
        except asyncio.CancelledError:
            async with self._condition:
                if waiter.granted:
                    self._active -= 1
                    self._drain_locked()
                else:
                    try:
                        self._waiters.remove(waiter)
                    except ValueError:
                        pass
            raise

        async with self._condition:
            waited_ms = (time.monotonic_ns() - waiter.enqueued_ns) / 1_000_000
            return Admission(waited_ms, self._snapshot_locked())

    async def release(self) -> LimiterSnapshot:
        async with self._condition:
            if self._active <= 0:
                raise RuntimeError(f"{self.name} released without an active slot")
            self._active -= 1
            self._drain_locked()
            return self._snapshot_locked()

    async def set_limit(self, new_limit: int) -> LimiterSnapshot:
        if new_limit <= 0:
            raise ValueError("limit must be positive")
        async with self._condition:
            self._limit = new_limit
            self._drain_locked()
            return self._snapshot_locked()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[Admission]:
        admission = await self.acquire()
        try:
            yield admission
        finally:
            await self.release()

    def _snapshot_locked(self) -> LimiterSnapshot:
        return LimiterSnapshot(
            name=self.name,
            limit=self._limit,
            active=self._active,
            queue_depth=len(self._waiters),
        )

    def _drain_locked(self) -> None:
        while self._waiters and self._active < self._limit:
            waiter = self._waiters.popleft()
            if waiter.future.done():
                continue
            waiter.granted = True
            self._active += 1
            waiter.future.set_result(None)

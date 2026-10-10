from __future__ import annotations

import asyncio

import pytest

from agentcc.admission.limiter import AdjustableFifoLimiter, LimiterQueueFull


@pytest.mark.asyncio
async def test_fifo_order_and_no_oversubscription() -> None:
    limiter = AdjustableFifoLimiter("test", limit=1, queue_capacity=3)
    first = await limiter.acquire()
    assert first.snapshot.active == 1
    order: list[int] = []

    async def contender(identifier: int) -> None:
        async with limiter.slot():
            order.append(identifier)
            snapshot = await limiter.snapshot()
            assert snapshot.active == 1

    tasks = [asyncio.create_task(contender(index)) for index in range(3)]
    await asyncio.sleep(0)
    assert (await limiter.snapshot()).queue_depth == 3
    await limiter.release()
    await asyncio.gather(*tasks)
    assert order == [0, 1, 2]
    assert (await limiter.snapshot()).active == 0


@pytest.mark.asyncio
async def test_downscale_does_not_preempt_active_work() -> None:
    limiter = AdjustableFifoLimiter("test", limit=2, queue_capacity=2)
    await limiter.acquire()
    await limiter.acquire()
    snapshot = await limiter.set_limit(1)
    assert snapshot.active == 2
    assert snapshot.limit == 1
    waiter = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0)
    await limiter.release()
    assert not waiter.done()
    await limiter.release()
    await waiter
    assert (await limiter.snapshot()).active == 1
    await limiter.release()


@pytest.mark.asyncio
async def test_cancelled_waiter_is_removed_and_queue_is_bounded() -> None:
    limiter = AdjustableFifoLimiter("test", limit=1, queue_capacity=1)
    await limiter.acquire()
    waiter = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0)
    with pytest.raises(LimiterQueueFull):
        await limiter.acquire()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert (await limiter.snapshot()).queue_depth == 0
    await limiter.release()


@pytest.mark.asyncio
async def test_context_manager_releases_on_exception() -> None:
    limiter = AdjustableFifoLimiter("test", limit=1, queue_capacity=1)
    with pytest.raises(RuntimeError):
        async with limiter.slot():
            raise RuntimeError("boom")
    assert (await limiter.snapshot()).active == 0

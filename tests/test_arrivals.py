from __future__ import annotations

from agentcc.config import ArrivalConfig
from agentcc.loadgen.arrivals import arrival_offsets


def test_seeded_arrivals_are_repeatable_and_monotonic() -> None:
    config = ArrivalConfig(kind="poisson", request_rate=4, num_requests=20)
    first = arrival_offsets(config, 42)
    second = arrival_offsets(config, 42)
    assert first == second
    assert first == sorted(first)
    assert first[0] == 0


def test_burst_arrivals_share_scheduled_times() -> None:
    config = ArrivalConfig(kind="burst", request_rate=10, num_requests=6, burst_size=3)
    assert arrival_offsets(config, 1) == [0.0, 0.0, 0.0, 0.3, 0.3, 0.3]

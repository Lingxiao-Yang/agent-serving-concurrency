from __future__ import annotations

import random

from agentcc.config import ArrivalConfig


def arrival_offsets(config: ArrivalConfig, seed: int) -> list[float]:
    """Return scheduled seconds from run start without coupling to completions."""
    rng = random.Random(seed)
    count = config.num_requests
    if config.kind == "steady":
        return [index / config.request_rate for index in range(count)]
    if config.kind == "burst":
        burst_interval = config.burst_size / config.request_rate
        return [(index // config.burst_size) * burst_interval for index in range(count)]

    offsets: list[float] = []
    elapsed = 0.0
    for _ in range(count):
        if config.kind == "poisson":
            delay = rng.expovariate(config.request_rate)
        else:
            scale = 1.0 / (config.request_rate * config.burstiness)
            delay = rng.gammavariate(config.burstiness, scale)
        offsets.append(elapsed)
        elapsed += delay
    return offsets

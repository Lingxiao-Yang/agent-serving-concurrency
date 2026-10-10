from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest


class ServiceMetrics:
    def __init__(self, service: str) -> None:
        self.registry = CollectorRegistry()
        self.active = Gauge(
            "agentcc_active_slots",
            "Currently occupied admission slots",
            ["stage"],
            registry=self.registry,
        )
        self.limit = Gauge(
            "agentcc_stage_limit",
            "Current stage concurrency limit",
            ["stage"],
            registry=self.registry,
        )
        self.queue = Gauge(
            "agentcc_queue_depth",
            "Current admission queue depth",
            ["stage"],
            registry=self.registry,
        )
        self.requests = Counter(
            "agentcc_requests_total",
            "Terminal requests by status",
            ["service", "status"],
            registry=self.registry,
        )
        self.service = service

    def update_limiter(self, stage: str, active: int, limit: int, queue_depth: int) -> None:
        self.active.labels(stage=stage).set(active)
        self.limit.labels(stage=stage).set(limit)
        self.queue.labels(stage=stage).set(queue_depth)

    def terminal(self, status: str) -> None:
        self.requests.labels(service=self.service, status=status).inc()

    def render(self) -> bytes:
        return generate_latest(self.registry)

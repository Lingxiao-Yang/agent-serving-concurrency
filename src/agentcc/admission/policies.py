from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agentcc.config import RunConfig
from agentcc.schemas import Limits, LimitUpdate


@dataclass(frozen=True, slots=True)
class PolicySnapshot:
    completed: int = 0
    goodput: int = 0
    request_queue: int = 0
    model_queue: int = 0
    tool_queue: int = 0


class Policy(ABC):
    @abstractmethod
    def initial_limits(self) -> Limits:
        raise NotImplementedError

    def observe(self, snapshot: PolicySnapshot) -> None:
        del snapshot

    def maybe_update(self) -> LimitUpdate | None:
        return None


class StaticGlobalPolicy(Policy):
    def __init__(self, config: RunConfig) -> None:
        self._configured = config.limits

    def initial_limits(self) -> Limits:
        limits = self._configured
        return Limits(
            n=limits.n,
            k=limits.max_k,
            m=limits.max_m,
            max_n=limits.max_n,
            max_k=limits.max_k,
            max_m=limits.max_m,
        )


class StaticStagePolicy(Policy):
    def __init__(self, config: RunConfig) -> None:
        self._configured = config.limits

    def initial_limits(self) -> Limits:
        limits = self._configured
        return Limits(
            n=limits.max_n,
            k=limits.k,
            m=limits.m,
            max_n=limits.max_n,
            max_k=limits.max_k,
            max_m=limits.max_m,
        )


def policy_for(config: RunConfig) -> Policy:
    if config.policy.value == "static_global":
        return StaticGlobalPolicy(config)
    return StaticStagePolicy(config)

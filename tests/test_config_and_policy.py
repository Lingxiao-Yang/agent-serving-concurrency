from __future__ import annotations

from pathlib import Path

from agentcc.admission.policies import policy_for
from agentcc.config import load_run_config, load_tasks
from agentcc.schemas import PolicyKind

ROOT = Path(__file__).resolve().parents[1]


def test_config_and_fixture_hashes_are_deterministic() -> None:
    first = load_run_config(ROOT / "configs/cpu_smoke.yaml")
    second = load_run_config(ROOT / "configs/cpu_smoke.yaml")
    assert first.stable_hash() == second.stable_hash()
    tasks = load_tasks(first.workload.catalog)
    assert sorted(tasks) == ["analysis-region-mean", "sqlite-region-sales"]


def test_static_stage_uses_outer_safety_cap() -> None:
    config = load_run_config(ROOT / "configs/cpu_smoke.yaml")
    limits = policy_for(config).initial_limits()
    assert (limits.n, limits.k, limits.m) == (8, 2, 2)


def test_static_global_makes_internal_gates_nonbinding() -> None:
    config = load_run_config(ROOT / "configs/cpu_smoke.yaml")
    config.policy = PolicyKind.STATIC_GLOBAL
    limits = policy_for(config).initial_limits()
    assert (limits.n, limits.k, limits.m) == (4, 4, 4)

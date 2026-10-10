# Project status

Last updated: 2026-10-09.

## Current milestone

The repository contains a CPU-first, end-to-end agent-serving testbed. It uses
deterministic scripted inference so admission control, workloads, failure
handling, and measurements can be tested before consuming GPU allocation time.
The CPU results are engineering validation only; they do not support claims
about GPU performance or the benefit of adaptive policies.

## Implemented

- Python 3.12 package managed by `uv`, with pinned dependency resolution.
- FastAPI agent and tool services bound to localhost by default.
- Explicit LangGraph model/tool loop with action and deadline bounds.
- A shared adjustable FIFO limiter used for request (`N`), model (`M`), and
  tool-execution (`K`) admission.
- Non-preemptive downscaling, bounded queues, explicit rejection states, and
  cancellation-safe slot release. Timed-out process-pool work retains its `K`
  slot until the worker actually exits.
- Static global and stage-specific policy implementations and typed limit
  update records.
- Deterministic scripted and OpenAI-compatible vLLM model backends behind the
  same interface.
- Trusted SQLite and tabular-analysis tools executed by a fixed process pool.
- Seeded steady, burst, and mixed open-loop arrival schedules.
- Structured request summaries, event schemas, deterministic result/config
  hashes, and run manifests.
- Event invariant validation, summary analysis, and a latency/queue timeline.
- Prometheus metrics and optional OpenTelemetry propagation.
- Local Docker Compose observability scaffold and CI configuration.
- Apache-2.0 licensing and third-party provenance notes.

## Verification record

The current source tree passed local verification on 2026-10-09:

- Ruff formatting/lint checks.
- Mypy over 25 source files.
- 17 unit and integration tests (`17 passed`).
- A real two-process scripted smoke run with 10/10 terminal successes and
  independently correct workload results.
- Event-log invariant validation on the smoke output.

This verification includes the timeout-release hardening and documentation
reorganization prepared for the initial commit.

## Not implemented or not yet validated

- A live Qwen3-8B/vLLM trajectory on a GPU.
- A pinned model/tokenizer revision and environment capture for Lonestar6.
- Adaptive global or stage-specific policies.
- Replay equivalence, the full workload suite, statistical analysis, or a
  research-scale experiment matrix.
- Linux cgroup/resource-isolation validation. Windows tests establish software
  behavior only.
- Native virtual environment versus HPC-supported container deployment on
  Lonestar6.

## Reproduce the current CPU milestone

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy src
uv run pytest
uv run python experiments/run_smoke.py --config configs/cpu_smoke.yaml
```

Expected output is written under `results/cpu-smoke/`. Check the manifest and
run the invariant validator before treating a run as valid:

```bash
uv run agentcc validate-events results/cpu-smoke/events
```

## Ownership

- Chenrui: workload fixtures, independent validators, and load generation.
- Lingxiao: admission control, tool execution, and resource profiling.
- Both: schemas, integration tests, experiment review, and interpretation.

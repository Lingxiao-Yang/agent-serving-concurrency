# Agent Concurrency Control Testbed

This repository contains the CPU-first testbed for comparing global request
concurrency with stage-specific model and tool concurrency. The current
milestone uses deterministic scripted inference; the same graph can later call
Qwen3 through a vLLM OpenAI-compatible endpoint.

## Quick start

Requires Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras
uv run pytest
```

Start the two services in separate terminals:

```bash
uv run agentcc tool-service --config configs/cpu_smoke.yaml
uv run agentcc agent-service --config configs/cpu_smoke.yaml
```

Then run the open-loop smoke workload:

```bash
uv run agentcc loadgen --config configs/cpu_smoke.yaml
uv run agentcc validate-events results/cpu-smoke/events
```

The agent API listens on `127.0.0.1:8000`; the trusted internal tool service
listens on `127.0.0.1:8001`. Raw JSONL files under `results/<run-id>/` are the
authoritative experiment record.

## Documentation

- [Current status](docs/STATUS.md) records what is implemented, verified, and
  still missing.
- [Execution plan](docs/PLAN.md) defines the milestone gates from CPU smoke
  testing through the static GPU sweep and adaptive policies.
- [Lonestar6 notes](docs/TACC_LONESTAR6.md) map the testbed to TACC queues,
  storage, and Slurm constraints.
- [Project proposal](docs/proposal/proposal.pdf) contains the submitted project
  description; its LaTeX source lives beside it.

## GPU integration

`configs/gpu_smoke.yaml` targets Qwen3-8B on vLLM. Start vLLM separately with
the pinned model revision recorded in that configuration. GPU runs are a later
milestone and are not represented as completed results.

## Safety and scope

Only named, trusted local tools are accepted. The service never evaluates
client-supplied Python. Both internal services bind to localhost by default.

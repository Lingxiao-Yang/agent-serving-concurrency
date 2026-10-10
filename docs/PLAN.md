# Execution plan

This plan starts from the working scripted vertical slice and uses explicit
exit gates. A later phase begins only after the previous phase produces a
reproducible manifest and passes its invariants.

## Phase 0 — repository and platform baseline

1. Create the remote repository and protect the default branch.
2. Run lint, type checks, tests, and the scripted smoke run on a clean checkout.
3. Record a release tag for the CPU vertical slice.
4. Confirm the Lonestar6 allocation, queues, available Python/CUDA modules,
   outbound model-download policy, and supported container runtime.
5. Add a platform-probe command that records CPU topology, affinity, memory,
   GPU inventory, Slurm variables, modules, and storage locations.

Exit gate: a clean Windows checkout and a Lonestar6 compute-node checkout
produce identical task/fixture/result hashes for scripted inference.

## Phase 1 — CPU engineering pilot on Lonestar6

1. Run the scripted services and load generator inside one Slurm allocation.
2. Bind all HTTP endpoints to `127.0.0.1`; no cross-node networking is needed.
3. Exercise global limits `N={1,4,8}` and selected stage limits
   `(K,M)={(1,4),(2,2),(4,1)}`.
4. Run at least 100 requests per configuration.
5. Archive configuration, manifest, request/event JSONL, invariant report, and
   one latency/queue timeline.

Exit gate: no oversubscription, unmatched stage events, missing terminal states,
or incorrect workload results. These results remain system validation, not a
policy comparison.

## Phase 2 — single-GPU vertical slice

1. Use one A100 node in `gpu-a100-dev` for short interactive validation.
2. Pin Qwen3-8B model and tokenizer revisions, vLLM version, CUDA stack,
   sampling parameters, and environment/container identity.
3. Restrict vLLM to one visible GPU for the first run; leave the other devices
   unused until the single-GPU path is trustworthy.
4. Verify one complete model → tool → model trajectory.
5. Correlate request IDs across agent events, tool events, vLLM metrics, and
   traces.
6. Exercise malformed calls, timeouts, cancellation, and queue saturation with
   the live backend.

Exit gate: live answers pass the independent workload validators and every
request has a complete correlated trace without changing admission or workload
code.

## Phase 3 — static characterization

1. Select one fixed GPU type and record it for every run. Do not combine A100
   and H100 samples in the same comparison.
2. Sweep conservative `N`, `K`, and `M` values to find tool-limited,
   inference-limited, and balanced regimes.
3. Use identical seeded arrivals and workload mixes across policies.
4. Collect latency distributions, deadline attainment, throughput, queue waits,
   active counts, CPU use, GPU use, and correctness.
5. Repeat configurations and report uncertainty; reject runs with invariant or
   correctness failures.

Exit gate: at least one stable candidate from each resource regime, with
repeated runs and no confounding platform changes.

## Phase 4 — adaptive policies

1. Implement global adaptation through the existing `Policy` interface,
   changing only `N` while `K` and `M` remain safe and nonbinding.
2. Implement stage adaptation with fixed safety-cap `N` and adjustable `K/M`.
3. Define observation windows, cooldowns, bounds, overload signals, and rollback
   behavior before running comparisons.
4. Compare against matched static baselines using the Phase 3 workload seeds.

Exit gate: controllers remain within safety maxima, decisions are reconstructible
from logs, and claimed benefits are supported by correctness-preserving repeated
measurements.

## Phase 5 — research artifact

Implement replay validation, expand both workload families, freeze analysis
scripts, publish experiment matrices, and document all exclusions. Retain raw
JSONL as the authoritative dataset; dashboards and traces are diagnostic views.

## Immediate next actions

1. Re-run the local checks after the latest limiter hardening.
2. Push the repository and enable CI.
3. Log into Lonestar6, run `taccinfo`, `qlimits`, and `module spider python`, and
   record the results without committing account identifiers.
4. Reproduce `cpu_smoke.yaml` in an interactive compute allocation.
5. Only then prepare the Qwen3/vLLM environment and single-trajectory GPU run.

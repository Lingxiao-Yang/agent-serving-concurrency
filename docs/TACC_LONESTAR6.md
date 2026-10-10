# Lonestar6 deployment notes

Source: the official [Lonestar6 User Guide](https://docs.tacc.utexas.edu/hpc/lonestar6/),
reviewed 2026-10-09. Queue limits can change; verify them with `qlimits` before
submitting a run.

## Why it is useful

Lonestar6 is a strong target for this project. An A100 node has 128 AMD EPYC CPU
cores, 256 GB RAM, and three 40 GB A100s. It can host vLLM, the agent and tool
services, and the load generator on one exclusive node. H100 nodes should be
treated as a separate platform rather than mixed into A100 measurements.

Use `gpu-a100-dev` for short validation and `gpu-a100` for production runs. GPU
jobs are charged by node-hour with a 15-minute minimum, so run nearby
configurations in one allocation and stop services when the matrix completes.

## Slurm constraints

Lonestar6 selects GPUs by partition. Do **not** use `--gres`,
`--gpus-per-task`, or `--mem`; its documented scheduler configuration rejects
these options. Do not request or exclude a named host.

Start an interactive GPU session with:

```bash
idev -p gpu-a100-dev -N 1 -n 1 -t 01:00:00
```

A batch header should start from this shape. Supply `-A` only when the account
has multiple projects.

```bash
#!/bin/bash
#SBATCH -J agentcc-smoke
#SBATCH -p gpu-a100-dev
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 01:00:00
#SBATCH -o slurm-%j.out
```

Run every service inside the allocation and bind it to localhost:

```text
load generator -> agent service :8000 -> vLLM :8002
                                   |
                                   +-> tool service :8001 -> process pool
```

For the first GPU run, `CUDA_VISIBLE_DEVICES=0` may restrict vLLM to one of the
GPUs assigned with the exclusive node. This is application configuration, not a
Slurm resource request.

## Storage

- `$WORK`: repository, small durable configuration, and selected archived
  results. It is not intended for high-intensity I/O and is not backed up.
- `$SCRATCH`: Python environment, model cache, raw event streams, and temporary
  results. Files inactive for more than 10 days are subject to purge.
- `/tmp`: node-local space for generated SQLite/CSV fixtures and high-frequency
  temporary files. It is erased when the job ends.
- `$HOME`: small account/configuration files only.

Copy retained manifests and results out of `$SCRATCH` before they become purge
candidates. Never put tokens in job scripts, manifests, or Git.

## First-session checklist

Run account and queue discovery on the login node, then perform installation and
computation only inside a compute allocation:

```bash
/usr/local/etc/taccinfo
qlimits
module reset
module spider python
module spider cuda
module spider apptainer
module spider singularity
```

Confirm the allocation and available SUs, queue access, current limits, Python
3.12/CUDA availability, the supported container runtime, and the approved way
to stage Hugging Face model files. The official guide recommends placing Python
virtual environments on `$SCRATCH`.

## Measurement adaptations

Keep agent/tool JSONL authoritative. Add Slurm job ID, partition, node name,
CPU affinity, `nvidia-smi` inventory, loaded modules, and threading variables to
each manifest. Use `sacct` for job accounting and sample resources from inside
the allocation. Docker Compose and cAdvisor are local/Linux aids; do not assume
they are available on the shared HPC system.

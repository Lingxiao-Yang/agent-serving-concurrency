from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from agentcc.telemetry.validation import read_events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    parser.add_argument("--output", type=Path, default=Path("timeline.png"))
    args = parser.parse_args()
    rows: list[dict[str, Any]] = list(read_events(args.events))
    if not rows:
        raise SystemExit("no events")
    start = min(row["monotonic_ns"] for row in rows)
    _, axis = plt.subplots(figsize=(10, 4))
    for stage in ("n", "m", "k"):
        selected = [row for row in rows if row["stage"] == stage and row.get("active") is not None]
        axis.step(
            [(row["monotonic_ns"] - start) / 1e9 for row in selected],
            [row["active"] for row in selected],
            where="post",
            label=f"{stage} active",
        )
    axis.set(xlabel="seconds", ylabel="active slots", title="Admission-control timeline")
    axis.legend()
    axis.grid(alpha=0.25)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(args.output, dpi=160)
    print(json.dumps({"output": str(args.output), "events": len(rows)}))


if __name__ == "__main__":
    main()

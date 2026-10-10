from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("requests", type=Path)
    args = parser.parse_args()
    records: list[dict[str, Any]] = [
        json.loads(line) for line in args.requests.read_text(encoding="utf-8").splitlines()
    ]
    latencies = [float(item["schedule_relative_latency_ms"]) for item in records]
    summary = {
        "requests": len(records),
        "correct": sum(bool(item["correct"]) for item in records),
        "mean_ms": statistics.fmean(latencies),
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

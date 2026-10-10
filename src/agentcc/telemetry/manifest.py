from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from agentcc.config import RunConfig

THREAD_ENV = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def _file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_revision(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def write_manifest(config: RunConfig, root: Path) -> Path:
    config.run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": config.run_id,
        "config": config.model_dump(mode="json"),
        "config_sha256": config.stable_hash(),
        "uv_lock_sha256": _file_hash(root / "uv.lock"),
        "git_revision": _git_revision(root),
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "thread_environment": {key: os.getenv(key) for key in THREAD_ENV},
        "container_images": {
            "agentcc": os.getenv("AGENTCC_IMAGE_DIGEST"),
            "vllm": os.getenv("VLLM_IMAGE_DIGEST"),
        },
    }
    destination = config.run_dir / "manifest.json"
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return destination

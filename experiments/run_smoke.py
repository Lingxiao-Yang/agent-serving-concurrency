from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

from agentcc.config import load_run_config
from agentcc.loadgen.runner import run_load
from agentcc.telemetry.validation import validate_events


async def wait_ready(url: str, process: asyncio.subprocess.Process) -> None:
    async with httpx.AsyncClient() as client:
        for _ in range(100):
            if process.returncode is not None:
                raise RuntimeError(f"service exited with code {process.returncode}")
            try:
                response = await client.get(f"{url}/health", timeout=0.25)
                if response.is_success:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
    raise TimeoutError(f"service did not become ready: {url}")


async def run(root: Path, config_path: str) -> None:
    config = load_run_config(root / config_path)
    commands = [
        [sys.executable, "-m", "agentcc.cli", "tool-service", "--config", config_path],
        [sys.executable, "-m", "agentcc.cli", "agent-service", "--config", config_path],
    ]
    processes = [
        await asyncio.create_subprocess_exec(*command, cwd=root) for command in commands
    ]
    try:
        await wait_ready(config.services.tool_url, processes[0])
        await wait_ready(config.services.agent_url, processes[1])
        output = await run_load(config, repository_root=root)
        errors = validate_events(config.run_dir / "events")
        if errors:
            raise RuntimeError("; ".join(errors))
        print(output)
    finally:
        for process in reversed(processes):
            process.terminate()
        for process in reversed(processes):
            await asyncio.wait_for(process.wait(), timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/cpu_smoke.yaml")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    asyncio.run(run(root, args.config))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import uvicorn

from agentcc.agent.service import create_agent_app
from agentcc.config import load_run_config
from agentcc.loadgen.runner import run_load
from agentcc.telemetry.manifest import write_manifest
from agentcc.telemetry.validation import validate_events
from agentcc.tools.service import create_tool_app


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentcc")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, default_port in (("agent-service", 8000), ("tool-service", 8001)):
        service = commands.add_parser(name)
        service.add_argument("--config", required=True)
        service.add_argument("--host", default="127.0.0.1")
        service.add_argument("--port", type=int, default=default_port)
    loadgen = commands.add_parser("loadgen")
    loadgen.add_argument("--config", required=True)
    validate = commands.add_parser("validate-events")
    validate.add_argument("path")
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--config", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    root = Path.cwd().resolve()
    if args.command == "validate-events":
        errors = validate_events(Path(args.path))
        if errors:
            for error in errors:
                print(error)
            raise SystemExit(1)
        print("event validation passed")
        return

    config = load_run_config(args.config)
    if args.command == "manifest":
        print(write_manifest(config, root))
    elif args.command == "loadgen":
        print(asyncio.run(run_load(config, repository_root=root)))
    elif args.command == "agent-service":
        uvicorn.run(create_agent_app(config), host=args.host, port=args.port)
    elif args.command == "tool-service":
        uvicorn.run(
            create_tool_app(config, repository_root=root), host=args.host, port=args.port
        )


if __name__ == "__main__":
    main()

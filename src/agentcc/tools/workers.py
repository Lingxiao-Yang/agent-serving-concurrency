from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path
from statistics import fmean
from typing import Any


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def execute_tool(tool_name: str, arguments: dict[str, Any], repository_root: str) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    value: Any
    if tool_name == "sqlite_query":
        value = _sqlite_query(arguments, root)
    elif tool_name == "data_analysis":
        value = _data_analysis(arguments, root)
    else:
        raise ValueError(f"unknown trusted tool: {tool_name}")
    return {"value": value, "result_hash": canonical_hash(value)}


def _safe_fixture(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if root not in candidate.parents:
        raise ValueError("fixture path escapes repository root")
    if not candidate.is_file():
        raise ValueError(f"fixture does not exist: {relative}")
    return candidate


def _sqlite_query(arguments: dict[str, Any], root: Path) -> list[list[Any]]:
    seed_path = _safe_fixture(root, str(arguments["seed_sql"]))
    query = str(arguments["query"])
    if not query.lstrip().lower().startswith("select"):
        raise ValueError("sqlite_query accepts SELECT statements only")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(seed_path.read_text(encoding="utf-8"))
        rows = connection.execute(query).fetchall()
        return [list(row) for row in rows]
    finally:
        connection.close()


def _data_analysis(arguments: dict[str, Any], root: Path) -> dict[str, float | int]:
    dataset = _safe_fixture(root, str(arguments["dataset"]))
    group_by = str(arguments["group_by"])
    value_column = str(arguments["value_column"])
    operation = str(arguments["operation"])
    groups: dict[str, list[float]] = {}
    with dataset.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            groups.setdefault(row[group_by], []).append(float(row[value_column]))

    if operation == "sum":
        return {key: sum(values) for key, values in sorted(groups.items())}
    if operation == "mean":
        return {key: fmean(values) for key, values in sorted(groups.items())}
    if operation == "count":
        return {key: len(values) for key, values in sorted(groups.items())}
    raise ValueError(f"unsupported analysis operation: {operation}")

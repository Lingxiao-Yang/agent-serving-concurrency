from __future__ import annotations

from pathlib import Path

import pytest

from agentcc.config import load_tasks
from agentcc.loadgen.runner import answers_equal
from agentcc.tools.workers import canonical_hash, execute_tool

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("task_id", ["sqlite-region-sales", "analysis-region-mean"])
def test_trusted_tools_match_gold_answers(task_id: str) -> None:
    task = load_tasks(ROOT / "workloads/tasks.yaml")[task_id]
    result = execute_tool(task.tool_name, task.tool_arguments, str(ROOT))
    assert answers_equal(result["value"], task.expected)
    assert result["result_hash"] == canonical_hash(task.expected)


def test_sqlite_tool_rejects_mutation() -> None:
    with pytest.raises(ValueError, match="SELECT"):
        execute_tool(
            "sqlite_query",
            {"seed_sql": "workloads/sqlite/fixture.sql", "query": "DROP TABLE orders"},
            str(ROOT),
        )


def test_fixture_path_cannot_escape_repository() -> None:
    with pytest.raises(ValueError, match="escapes"):
        execute_tool(
            "data_analysis",
            {
                "dataset": "../secret.csv",
                "group_by": "x",
                "value_column": "y",
                "operation": "sum",
            },
            str(ROOT),
        )

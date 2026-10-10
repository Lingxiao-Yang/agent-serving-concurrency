from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Literal, cast

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agentcc.config import ModelConfig
from agentcc.schemas import JsonValue, TaskSpec, ToolCall


class ModelDecision(BaseModel):
    kind: Literal["tool", "final", "error"]
    tool_call: ToolCall | None = None
    answer: JsonValue = None
    error: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class ModelBackend(ABC):
    @abstractmethod
    async def decide(
        self,
        task: TaskSpec,
        messages: list[dict[str, Any]],
        last_tool_result: JsonValue,
        action_count: int,
    ) -> ModelDecision:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class ScriptedModelBackend(ModelBackend):
    def __init__(self, delay_ms: float) -> None:
        self.delay_s = delay_ms / 1000

    async def decide(
        self,
        task: TaskSpec,
        messages: list[dict[str, Any]],
        last_tool_result: JsonValue,
        action_count: int,
    ) -> ModelDecision:
        del messages
        await asyncio.sleep(self.delay_s)
        if action_count == 0:
            return ModelDecision(
                kind="tool",
                tool_call=ToolCall(
                    call_id=f"{task.task_id}-call-1",
                    name=task.tool_name,
                    arguments=task.tool_arguments,
                ),
                input_tokens=max(1, len(task.prompt.split())),
                output_tokens=8,
            )
        return ModelDecision(
            kind="final",
            answer=last_tool_result,
            input_tokens=max(1, len(task.prompt.split())) + 8,
            output_tokens=4,
        )


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "sqlite_query": {
        "type": "function",
        "function": {
            "name": "sqlite_query",
            "description": "Run a read-only query against the task's SQLite fixture.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seed_sql": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["seed_sql", "query"],
                "additionalProperties": False,
            },
        },
    },
    "data_analysis": {
        "type": "function",
        "function": {
            "name": "data_analysis",
            "description": "Compute a grouped aggregate over the task's CSV fixture.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {"type": "string"},
                    "group_by": {"type": "string"},
                    "value_column": {"type": "string"},
                    "operation": {"enum": ["sum", "mean", "count"]},
                },
                "required": ["dataset", "group_by", "value_column", "operation"],
                "additionalProperties": False,
            },
        },
    },
}


class VllmModelBackend(ModelBackend):
    def __init__(self, config: ModelConfig) -> None:
        self.config = config
        self.client = AsyncOpenAI(base_url=config.base_url, api_key="EMPTY")

    async def decide(
        self,
        task: TaskSpec,
        messages: list[dict[str, Any]],
        last_tool_result: JsonValue,
        action_count: int,
    ) -> ModelDecision:
        current = list(messages)
        if not current:
            current = [
                {
                    "role": "system",
                    "content": (
                        "Solve the task using only the supplied trusted tool. "
                        "Use the exact fixture path and fields stated by the user. "
                        "After the tool responds, return only the resulting JSON value."
                    ),
                },
                {"role": "user", "content": task.prompt},
            ]
        elif last_tool_result is not None and current[-1].get("role") != "tool":
            current.append(
                {
                    "role": "tool",
                    "tool_call_id": f"{task.task_id}-call-{action_count}",
                    "content": json.dumps(last_tool_result, sort_keys=True),
                }
            )

        response = await self.client.chat.completions.create(
            model=self.config.model,
            messages=current,  # type: ignore[arg-type]
            tools=cast(Any, [TOOL_SCHEMAS[task.tool_name]]),
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": self.config.enable_thinking}},
        )
        choice = response.choices[0]
        message = choice.message
        dumped = message.model_dump(exclude_none=True)
        updated = current + [dumped]
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        if message.tool_calls:
            call = message.tool_calls[0]
            if call.type != "function":
                return ModelDecision(kind="error", error="unsupported_custom_tool_call")
            function = call.function
            try:
                arguments = json.loads(function.arguments)
            except json.JSONDecodeError as exc:
                return ModelDecision(kind="error", error=f"malformed_tool_arguments: {exc}")
            return ModelDecision(
                kind="tool",
                tool_call=ToolCall(call_id=call.id, name=function.name, arguments=arguments),
                messages=updated,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        return ModelDecision(
            kind="final",
            answer=message.content,
            messages=updated,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def close(self) -> None:
        await self.client.close()


def create_model_backend(config: ModelConfig) -> ModelBackend:
    if config.kind.value == "scripted":
        return ScriptedModelBackend(config.delay_ms)
    return VllmModelBackend(config)

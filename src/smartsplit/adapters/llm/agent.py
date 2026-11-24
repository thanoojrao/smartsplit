"""Anthropic-backed AgentModel: one model call of the agent loop, with tool use (SPEC 8.7).

The tools and the system prompt are fixed and come first, each marked for caching, so every
call of every turn reuses that prefix (SPEC 12.5). The assistant's content blocks are sent
back exactly as they came (thinking blocks are only valid unchanged).
"""

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import anthropic
from anthropic.types import Message, MessageParam, TextBlockParam, ToolParam

from smartsplit.adapters.llm.calls import call_once_more
from smartsplit.ports.agent import (
    AgentRequest,
    ModelStep,
    ModelUsage,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from smartsplit.ports.llm import CountCall

log = logging.getLogger("smartsplit.llm")


class AnthropicAgent:
    """Adaptive thinking at low effort: chat turns are short, and latency matters."""

    def __init__(self, client: anthropic.Anthropic, *, model: str, max_tokens: int) -> None:
        self._client = client
        self.model = model
        self._max_tokens = max_tokens

    def step(self, request: AgentRequest, count_call: CountCall) -> ModelStep:
        """Raises LlmUnavailableError if the call fails twice (or once, for a setup error)."""
        messages = _messages(request)
        response = call_once_more(
            "agent",
            lambda timeout: self._client.messages.create(
                model=self.model,
                max_tokens=self._max_tokens,
                system=_system(request.system),
                tools=_tools(request.tools),
                tool_choice={"type": "none"} if request.final else {"type": "auto"},
                output_config={"effort": "low"},
                messages=messages,
                timeout=timeout,
            ),
            timeout_seconds=request.timeout_seconds,
            count_call=count_call,
        )
        return _step(response)


def _system(text: str) -> list[TextBlockParam]:
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _tools(specs: Sequence[ToolSpec]) -> list[ToolParam]:
    tools: list[ToolParam] = [
        {"name": s.name, "description": s.description, "input_schema": dict(s.input_schema)}
        for s in specs
    ]
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools


def _messages(request: AgentRequest) -> list[MessageParam]:
    messages: list[MessageParam] = [{"role": "user", "content": request.turn_input}]
    for step, results in request.history:
        assistant: MessageParam = {"role": "assistant", "content": _assistant(step)}
        answers: MessageParam = {"role": "user", "content": [_result(r) for r in results]}
        messages += [assistant, answers]
    return messages


def _assistant(step: ModelStep) -> list[Any]:
    if step.replay:
        return [dict(block) for block in step.replay]
    blocks: list[dict[str, object]] = [{"type": "text", "text": step.text}] if step.text else []
    blocks += [
        {"type": "tool_use", "id": c.id, "name": c.name, "input": dict(c.arguments)}
        for c in step.tool_calls
    ]
    return blocks


def _result(result: ToolResult) -> Any:
    body: dict[str, object] = (
        {"ok": True, **result.data, "shown_to_the_chat": list(result.shown)}
        if result.ok
        else {"ok": False, "reason": result.error}
    )
    return {
        "type": "tool_result",
        "tool_use_id": result.call_id,
        "content": json.dumps(body, ensure_ascii=False, default=str),
        "is_error": not result.ok,
    }


def _step(response: Message) -> ModelStep:
    """Tool calls to run, or the reply. A refusal or a cut-off answer says nothing."""
    usage = ModelUsage(
        response.usage.input_tokens,
        response.usage.cache_read_input_tokens or 0,
        response.usage.cache_creation_input_tokens or 0,
        response.usage.output_tokens,
    )
    if response.stop_reason not in ("end_turn", "tool_use"):
        log.warning("agent step ended early", extra={"stop_reason": response.stop_reason})
        return ModelStep((), "", usage)
    calls = tuple(
        ToolCall(b.id, b.name, _arguments(b.input))
        for b in response.content
        if b.type == "tool_use"
    )
    text = "\n".join(b.text for b in response.content if b.type == "text")
    replay = tuple(block.to_dict() for block in response.content)
    return ModelStep(calls, text, usage, replay)


def _arguments(raw: object) -> Mapping[str, object]:
    return raw if isinstance(raw, dict) else {}

"""The agent model port: one model call of the conversation loop (SPEC 8.7, CONTRACTS 4.2)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from smartsplit.ports.llm import CountCall


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What one tool call came to: `data` for the model, `shown` appended to the reply."""

    call_id: str
    ok: bool
    data: Mapping[str, object]
    error: str | None
    shown: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ModelStep:
    """Tool calls to run, or (with none) the model's part of the reply."""

    tool_calls: tuple[ToolCall, ...]
    text: str | None
    usage: ModelUsage = field(default_factory=ModelUsage)
    replay: tuple[Mapping[str, object], ...] = ()
    """The provider's own content blocks for this step, sent back unchanged with the history
    (e.g. thinking blocks that are only valid as they were produced); opaque to services."""


@dataclass(frozen=True, slots=True)
class AgentRequest:
    system: str
    tools: tuple[ToolSpec, ...]
    turn_input: str
    history: tuple[tuple[ModelStep, tuple[ToolResult, ...]], ...]
    """This turn's earlier steps and their results only."""
    timeout_seconds: float
    final: bool = False
    """The last allowed step: no tool may be called, so the model must write its reply. The
    tools stay listed, which keeps the cached prefix (and the earlier tool calls) valid."""


class AgentModel(Protocol):
    def step(self, request: AgentRequest, count_call: CountCall) -> ModelStep:
        """One model step within `request.timeout_seconds` in all (a retry gets what is left);
        raises LlmUnavailableError."""
        ...

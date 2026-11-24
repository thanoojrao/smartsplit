"""The agent loop: model → tool calls → results → model, until it writes its reply (SPEC 8.1).

At most `agent_max_steps` model calls; on the last one no tool may be called, so the model must
say what it did (reaching the limit is not a failure). Each call's timeout is the smaller of
the per-call limit and the time left for the message; a call that fails, or a deadline that
passes, raises LlmUnavailableError and the caller rolls the turn back.
"""

from dataclasses import dataclass, field
from datetime import datetime

from smartsplit.ports.agent import AgentModel, AgentRequest, ModelStep, ModelUsage, ToolResult
from smartsplit.ports.llm import CountCall, LlmUnavailableError
from smartsplit.ports.system import Clock
from smartsplit.services.agent_prompt import SYSTEM_PROMPT
from smartsplit.services.tools.catalog import ALL_TOOLS, TOOL_SPECS
from smartsplit.services.tools.registry import run_call
from smartsplit.services.turn import Turn


@dataclass(slots=True)
class LoopResult:
    """The model's words and what the loop did, for the per-turn log line (SPEC 12.4)."""

    text: str = ""
    steps: int = 0
    tools: list[tuple[str, bool]] = field(default_factory=list)
    usage: ModelUsage = field(default_factory=ModelUsage)


def run_loop(
    turn: Turn,
    model: AgentModel,
    turn_input: str,
    *,
    clock: Clock,
    deadline: datetime,
    count_call: CountCall,
) -> LoopResult:
    """Run the turn's model calls and tools; returns the model's (uncleaned) reply text."""
    settings = turn.settings
    history: list[tuple[ModelStep, tuple[ToolResult, ...]]] = []
    result = LoopResult()
    for step in range(settings.agent_max_steps):
        left = (deadline - clock.now()).total_seconds()
        if left <= 0:
            raise LlmUnavailableError("the message deadline passed")
        last = step == settings.agent_max_steps - 1
        request = AgentRequest(
            SYSTEM_PROMPT,
            TOOL_SPECS,
            turn_input,
            tuple(history),
            min(settings.llm_timeout_seconds, left),
            final=last,
        )
        answer = model.step(request, count_call)
        result.steps += 1
        result.usage = _add(result.usage, answer.usage)
        if not answer.tool_calls or last:
            result.text = answer.text or ""
            return result
        results = tuple(run_call(turn, call, ALL_TOOLS) for call in answer.tool_calls)
        result.tools += [
            (call.name, r.ok) for call, r in zip(answer.tool_calls, results, strict=True)
        ]
        history.append((answer, results))
    return result


def _add(total: ModelUsage, more: ModelUsage) -> ModelUsage:
    return ModelUsage(
        total.input_tokens + more.input_tokens,
        total.cache_read_tokens + more.cache_read_tokens,
        total.cache_write_tokens + more.cache_write_tokens,
        total.output_tokens + more.output_tokens,
    )

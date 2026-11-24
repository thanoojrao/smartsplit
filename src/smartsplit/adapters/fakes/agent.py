"""ScriptedAgent: plays a list of model steps and records what it was sent (SPEC 8.7).

Tests and `smartsplit demo` drive the real tools through it. A step is a ModelStep, or a
function of the request (to pick a handle out of the turn input) that returns one. When the
script runs out, the bot says nothing.
"""

import json
import re
from collections.abc import Callable, Iterable
from itertools import count

from smartsplit.ports.agent import AgentRequest, ModelStep, ToolCall
from smartsplit.ports.llm import CountCall

type Step = ModelStep | Callable[[AgentRequest], ModelStep]

_CALL_IDS = count(1)


def call(tool: str, /, **arguments: object) -> ModelStep:
    """One tool call."""
    return calls((tool, arguments))


def calls(*tool_calls: tuple[str, dict[str, object]]) -> ModelStep:
    """Several tool calls in one step."""
    return ModelStep(
        tuple(ToolCall(f"call_{next(_CALL_IDS)}", name, args) for name, args in tool_calls), None
    )


def say(text: str = "") -> ModelStep:
    """The model's reply: no tool calls."""
    return ModelStep((), text)


def _seen(request: AgentRequest) -> str:
    """The turn input, then what this turn's tool results returned (their handles count)."""
    results = [json.dumps(dict(r.data)) for _, step in request.history for r in step]
    return "\n".join([request.turn_input, *results])


def handle_of(request: AgentRequest, name: str) -> str:
    """The handle the turn input (or a tool result this turn) gave a person, draft, bill or
    group called `name` (its first mention), e.g. `handle_of(request, "Sam")` → "P2"."""
    found = re.search(rf"\b([PBDGQAT]\d+) \"?{re.escape(name)}\b", request.turn_input) or (
        re.search(rf'"([PBDGQAT]\d+)", "name": "{re.escape(name)}"', _seen(request))
    )
    if found is None:
        raise LookupError(f"no handle for {name!r} in the turn input")
    return found.group(1)


def first_handle(request: AgentRequest, prefix: str) -> str:
    """The first handle with this prefix in the turn input or this turn's results ("D" → "D1")."""
    found = re.search(rf"\b({prefix}\d+)\b", _seen(request))
    if found is None:
        raise LookupError(f"no {prefix} handle in the turn input")
    return found.group(1)


class ScriptedAgent:
    """Plays queued steps in order; `requests` records every request it was sent."""

    def __init__(self, steps: Iterable[Step] = ()) -> None:
        self._steps: list[Step] = list(steps)
        self.requests: list[AgentRequest] = []

    def queue(self, *steps: Step) -> None:
        self._steps += steps

    @property
    def pending(self) -> int:
        return len(self._steps)

    def step(self, request: AgentRequest, count_call: CountCall) -> ModelStep:
        count_call()
        self.requests.append(request)
        if not self._steps:
            return say()
        step = self._steps.pop(0)
        return step(request) if callable(step) else step

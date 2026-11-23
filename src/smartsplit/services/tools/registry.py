"""Running one tool call: decode the arguments, check who may use it here, run it inside a
savepoint, and return its result with the blocks it showed (SPEC 8.3, CONTRACTS 4.2).

Tools are plain services: they check permissions, compute, store and return; they never call
the model. A refused call (a short reason the model can act on) leaves nothing behind.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from smartsplit.domain.codec import Json, decode
from smartsplit.ports.agent import ToolCall, ToolResult, ToolSpec
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.tools.schema import complete, object_schema
from smartsplit.services.turn import Turn

type Access = Literal["members", "past_members", "anyone"]
"""Who may use a tool in a group chat; in a personal chat anyone may (SPEC 10.3)."""

type Data = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Tool[A]:
    name: str
    description: str
    args: type[A]
    run: Callable[[Turn, A], Data]
    access: Access = "members"

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, object_schema(self.args, tagged=False))


def run_call(turn: Turn, call: ToolCall, tools: Sequence[Tool[Any]]) -> ToolResult:
    """One tool call's result; never raises for a refusal or bad arguments."""
    tool = next((t for t in tools if t.name == call.name), None)
    if tool is None:
        return _refused(call, f"There's no tool called {call.name}.")
    try:
        args = decode(cast(Json, complete(dict(call.arguments), tool.args)), tool.args)
    except (ValueError, TypeError) as error:
        return _refused(call, f"Those arguments don't fit {call.name}: {error}")
    shown_before, elsewhere_before = len(turn.shown), len(turn.elsewhere)
    changed_before, acted_before = set(turn.changed_drafts), turn.acted
    try:
        _check_access(turn, tool.access)
        with turn.uow.savepoint():
            data = tool.run(turn, args)
    except NotAllowedError as refusal:
        del turn.shown[shown_before:]
        del turn.elsewhere[elsewhere_before:]
        turn.changed_drafts, turn.acted = changed_before, acted_before
        return _refused(call, str(refusal))
    shown = tuple(said.text for said in turn.shown[shown_before:])
    return ToolResult(call.id, True, data, None, shown)


def _refused(call: ToolCall, reason: str) -> ToolResult:
    return ToolResult(call.id, False, {}, reason, ())


def _check_access(turn: Turn, access: Access) -> None:
    """In a group, tools are for its members; people who left may still ask for balances,
    and anyone may join (SPEC 10.3, B2)."""
    group_id = turn.conversation.group_id
    if group_id is None or access == "anyone":
        return
    if turn.speaker.id in current_member_ids(turn.uow, group_id):
        return
    was_member = any(
        m.person_id == turn.speaker.id for m in turn.uow.memberships.for_group(group_id)
    )
    if access == "past_members" and was_member:
        return
    raise NotAllowedError(f'{turn.speaker.display_name} isn\'t in this group yet: say "join".')

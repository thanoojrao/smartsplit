"""Pending actions: what code confirms (SPEC 8.4).

A tool computes the exact effect and stores it here; the restatement is shown verbatim and
ends with whom the bot waits for. `confirm` applies it only on a later message, in this chat,
within 30 minutes, from the person asked, and only if the data hasn't changed since; otherwise
the effect is recomputed and asked again. So text in a receipt or a chat line can at most
produce a proposal that waits for the right person's own reply.
"""

from dataclasses import replace

from smartsplit.domain.enums import PromptKind, PromptStatus
from smartsplit.domain.prompts import (
    BillChangeEffect,
    ChatRef,
    PaymentEffect,
    PendingActionPayload,
    Prompt,
    RuleChangeEffect,
)
from smartsplit.domain.tools import (
    AddRule,
    ChangeBill,
    DeleteRule,
    NotReceived,
    PendingArgs,
    RecordPayment,
    SquareUp,
    UndoPayment,
)
from smartsplit.services.bill_changes import apply_bill_change, propose_change
from smartsplit.services.bill_status import bill_version
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.payments import (
    apply_payment,
    ledger_version,
    propose_payment,
    propose_reversal,
    propose_square_up,
)
from smartsplit.services.pending_types import Proposal
from smartsplit.services.rules_chat import RULE_VERSION, apply_rule_change, propose_rule_change
from smartsplit.services.text import name_for
from smartsplit.services.turn import Turn

TOOL_NAMES: dict[type, str] = {
    ChangeBill: "change_bill",
    RecordPayment: "record_payment",
    SquareUp: "square_up",
    NotReceived: "not_received",
    UndoPayment: "undo_payment",
    AddRule: "add_rule",
    DeleteRule: "delete_rule",
}


def compute(turn: Turn, args: PendingArgs) -> Proposal:
    """The effect of a pending tool, from arguments holding ids."""
    match args:
        case ChangeBill():
            return propose_change(turn, args)
        case RecordPayment():
            return propose_payment(turn, args)
        case SquareUp():
            return propose_square_up(turn, args)
        case NotReceived() | UndoPayment():
            return propose_reversal(turn, args)
        case AddRule() | DeleteRule():
            return propose_rule_change(turn, args)


def current_version(turn: Turn, payload: PendingActionPayload) -> int:
    """The version of the data the effect depends on, now."""
    effect = payload.effect
    match effect:
        case BillChangeEffect():
            return bill_version(turn.uow, effect.reverse_bill_id)
        case PaymentEffect():
            first = effect.settlements[0]
            return ledger_version(turn.uow, (first.from_id, first.to_id))
        case RuleChangeEffect():
            return RULE_VERSION


def propose(turn: Turn, args: PendingArgs) -> Prompt:
    """Store the proposal, replacing the speaker's open one of the same kind, and show it."""
    proposal = compute(turn, args)
    tool = TOOL_NAMES[type(args)]
    for open_one in open_actions(turn):
        payload = open_one.payload
        if (
            isinstance(payload, PendingActionPayload)
            and payload.tool == tool
            and open_one.asked_of == turn.speaker.id
        ):
            turn.uow.prompts.update(replace(open_one, status=PromptStatus.DROPPED))
    prompt = Prompt(
        turn.ids.new_id(),
        turn.conversation.key,
        None,
        PromptKind.PENDING_ACTION,
        PendingActionPayload(tool, args, proposal.effect, proposal.version, turn.message_id),
        PromptStatus.OPEN,
        turn.speaker.id,
        turn.speaker.id,
        turn.now,
        turn.now + turn.settings.pending_lasts,
        (),
    )
    turn.uow.prompts.add(prompt)
    turn.acted = True
    who = name_for(turn.uow, turn.viewer, turn.speaker.id)
    turn.show(
        f"{proposal.restatement}\nWaiting for {who} to say yes.", (ChatRef("action", prompt.id),)
    )
    return prompt


def open_actions(turn: Turn) -> list[Prompt]:
    """Pending actions still open in this chat; expired ones are dropped quietly."""
    still: list[Prompt] = []
    for prompt in turn.uow.prompts.for_conversation(turn.conversation.key, [PromptStatus.OPEN]):
        if prompt.kind is not PromptKind.PENDING_ACTION:
            continue
        if prompt.expires_at is not None and prompt.expires_at <= turn.now:
            turn.uow.prompts.update(replace(prompt, status=PromptStatus.DROPPED))
            continue
        still.append(prompt)
    return still


def confirm(turn: Turn, prompt_id: str) -> Prompt | None:
    """Apply the effect if this yes counts (SPEC 8.4). If the data changed since, the effect is
    worked out again and shown for a new yes: that new proposal is returned."""
    prompt, payload = _open(turn, prompt_id)
    if payload.proposed_in_message_id == turn.message_id:
        raise NotAllowedError(
            "That was only just proposed: the person asked has to say yes in a later message."
        )
    if prompt.asked_of != turn.speaker.id:
        who = name_for(turn.uow, turn.viewer, prompt.asked_of or "")
        raise NotAllowedError(f"Only {who} can confirm that.")
    if current_version(turn, payload) != payload.based_on_version:
        turn.uow.prompts.update(replace(prompt, status=PromptStatus.DROPPED))
        return propose(turn, payload.arguments)
    turn.uow.prompts.update(replace(prompt, status=PromptStatus.ANSWERED))
    turn.acted = True
    effect = payload.effect
    match effect:
        case BillChangeEffect():
            apply_bill_change(turn, effect)
        case PaymentEffect():
            apply_payment(turn, payload.tool, effect)
        case RuleChangeEffect():
            apply_rule_change(turn, effect)
    return None


def decline(turn: Turn, prompt_id: str) -> None:
    """ "No": the proposal is dropped; only the person asked can decline it."""
    prompt, _ = _open(turn, prompt_id)
    if prompt.asked_of != turn.speaker.id:
        raise NotAllowedError("Only the person asked can decline that.")
    turn.uow.prompts.update(replace(prompt, status=PromptStatus.DROPPED))
    turn.acted = True


def _open(turn: Turn, prompt_id: str) -> tuple[Prompt, PendingActionPayload]:
    prompt = next((p for p in open_actions(turn) if p.id == prompt_id), None)
    if prompt is None or not isinstance(prompt.payload, PendingActionPayload):
        raise NotAllowedError("That proposal has expired or isn't open any more.")
    return prompt, prompt.payload

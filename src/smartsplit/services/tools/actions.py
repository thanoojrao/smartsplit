"""Tools for rules, saved bills, payments and the rest (SPEC 8.3, 8.4).

Moving money and changing data other people rely on becomes a pending action: the effect is
computed and restated now, and applied only by `confirm_pending` on a later message from the
person asked. Your own rules apply at once.
"""

from typing import Any

from smartsplit.domain.tools import (
    AddRule,
    ChangeBill,
    ConfirmPending,
    DeclinePending,
    DeleteRule,
    NotReceived,
    PendingArgs,
    RecordPayment,
    Remind,
    SetNotifications,
    SquareUp,
    UndoPayment,
)
from smartsplit.services import pending
from smartsplit.services.personal import remind, set_notifications
from smartsplit.services.review import map_people
from smartsplit.services.rules import put_rule
from smartsplit.services.rules_chat import describe, rule_to_add, rule_to_delete
from smartsplit.services.tools import refs
from smartsplit.services.tools.registry import Data, Tool
from smartsplit.services.turn import Turn


def _proposed(turn: Turn, args: PendingArgs) -> Data:
    prompt = pending.propose(turn, args)
    handle = turn.handles.issue("action", prompt.id, "that")
    return {"action": handle, "waiting_for_yes_from": "the speaker, in a later message"}


def _add_rule(turn: Turn, args: AddRule) -> Data:
    subject = refs.person(turn, args.subject)
    ids_args = AddRule(subject, args.item, args.kind)
    if subject != turn.speaker.id:
        return _proposed(turn, ids_args)
    rule = rule_to_add(turn, ids_args)
    put_rule(turn.uow, rule)
    turn.acted = True
    turn.show(f"Noted: {describe(turn, rule)}.")
    return {"saved": True}


def _delete_rule(turn: Turn, args: DeleteRule) -> Data:
    subject = refs.person(turn, args.subject)
    ids_args = DeleteRule(subject, args.item)
    if subject != turn.speaker.id:
        return _proposed(turn, ids_args)
    rule = rule_to_delete(turn, ids_args)
    turn.uow.rules.delete(rule.id)
    turn.acted = True
    turn.show(f"Removed: {describe(turn, rule)}.")
    return {"deleted": True}


def _change_bill(turn: Turn, args: ChangeBill) -> Data:
    bill = refs.bill(turn, args.bill)
    change = map_people(args.change, lambda h: refs.person(turn, h))
    return _proposed(turn, ChangeBill(bill.id, change, args.reason))


def _record_payment(turn: Turn, args: RecordPayment) -> Data:
    group = refs.group(turn, args.group) if args.group else None
    return _proposed(
        turn,
        RecordPayment(
            refs.person(turn, args.from_person),
            refs.person(turn, args.to_person),
            args.amount,
            group,
        ),
    )


def _square_up(turn: Turn, args: SquareUp) -> Data:
    return _proposed(turn, SquareUp(refs.person(turn, args.with_person)))


def _not_received(turn: Turn, args: NotReceived) -> Data:
    return _proposed(turn, NotReceived(refs.payment(turn, args.payment)))


def _undo_payment(turn: Turn, args: UndoPayment) -> Data:
    return _proposed(turn, UndoPayment(refs.payment(turn, args.payment)))


def _confirm_pending(turn: Turn, args: ConfirmPending) -> Data:
    again = pending.confirm(turn, refs.action(turn, args.action))
    if again is None:
        return {"done": True}
    return {
        "done": False,
        "why": "something changed meanwhile; it was worked out again and shown",
        "action": turn.handles.issue("action", again.id, "that"),
    }


def _decline_pending(turn: Turn, args: DeclinePending) -> Data:
    pending.decline(turn, refs.action(turn, args.action))
    return {"dropped": True}


def _remind(turn: Turn, args: Remind) -> Data:
    remind(turn, refs.person(turn, args.person))
    if turn.in_group:
        return {"reminder": "the speaker was told in their own chat whether it goes"}
    return {"reminder": "will be sent"}


def _set_notifications(turn: Turn, args: SetNotifications) -> Data:
    set_notifications(turn, args.on)
    return {"notifications": "on" if args.on else "off"}


ACTION_TOOLS: tuple[Tool[Any], ...] = (
    Tool(
        "add_rule",
        "A preference: exclude (never shares the item), soft_exclude (usually not: ask), "
        "only (it's theirs). About the speaker it applies at once; about others it waits "
        "for a yes.",
        AddRule,
        _add_rule,
    ),
    Tool(
        "delete_rule",
        'Delete a rule ("Raj drinks milk now").',
        DeleteRule,
        _delete_rule,
    ),
    Tool(
        "change_bill",
        'Propose an edit, delete or "not mine" for a saved bill (B); waits for a yes.',
        ChangeBill,
        _change_bill,
    ),
    Tool(
        "record_payment",
        "Propose recording a payment between the speaker and someone; waits for a yes.",
        RecordPayment,
        _record_payment,
        "past_members",
    ),
    Tool(
        "square_up",
        "Propose squaring up with someone across every group; waits for a yes.",
        SquareUp,
        _square_up,
        "past_members",
    ),
    Tool(
        "not_received",
        "Propose reversing a payment someone else recorded with the speaker; waits for a yes.",
        NotReceived,
        _not_received,
        "past_members",
    ),
    Tool(
        "undo_payment",
        "Propose undoing a payment the speaker recorded; waits for a yes.",
        UndoPayment,
        _undo_payment,
        "past_members",
    ),
    Tool(
        "confirm_pending",
        "The person asked said yes to a pending action (A) on a later message.",
        ConfirmPending,
        _confirm_pending,
        "past_members",
    ),
    Tool(
        "decline_pending",
        "The person asked said no to a pending action (A).",
        DeclinePending,
        _decline_pending,
        "past_members",
    ),
    Tool("remind", "Send someone who owes the speaker a friendly nudge.", Remind, _remind),
    Tool(
        "set_notifications",
        'Turn the speaker\'s messages and reminders off ("stop") or on ("start").',
        SetNotifications,
        _set_notifications,
        "anyone",
    ),
)

"""One command, inside the conversation's transaction: permissions, then the handler.

Handlers resolve every name before writing anything, so a NeedsClarificationError leaves
nothing half done; the orchestrator rolls back on NotAllowedError either way.
"""

from dataclasses import replace

from smartsplit.domain.commands import (
    Acknowledge,
    AddManualBill,
    AnswerPrompt,
    CancelDraft,
    Command,
    ConfirmDraft,
    Edit,
    FileIntoGroup,
    Help,
    JoinGroup,
    ShowBalances,
    ShowBillDetails,
    StartSplit,
    Unknown,
)
from smartsplit.domain.edits import EditOp
from smartsplit.domain.enums import DraftState, PromptKind
from smartsplit.domain.model import BillDraft
from smartsplit.domain.prompts import StoredImage
from smartsplit.domain.values import GroupContext, Override, PersonalContext
from smartsplit.services.answers import answerable, handle_answer
from smartsplit.services.bill_changes import (
    find_bill,
    propose_edit,
)
from smartsplit.services.drafting import (
    Who,
    active_draft,
    exact_override,
    manual_line,
    new_draft,
    present,
    who_for_group,
    who_for_personal,
)
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.lifecycle import ask_who_with
from smartsplit.services.membership import (
    ask_to_join,
)
from smartsplit.services.names import Directory, directory, group_directory
from smartsplit.services.prompting import drop
from smartsplit.services.receipt_flow import add_photo
from smartsplit.services.review import apply_edit, save
from smartsplit.services.routing import details, route
from smartsplit.services.saving import cancel, confirm
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.turn import Turn


def dispatch(turn: Turn, command: Command, photo: StoredImage | None = None) -> None:
    """Run one command for the speaker in this chat."""
    if turn.in_group and not _may_act_here(turn, command):
        ask_to_join(turn)
        return
    people = (
        group_directory(turn.uow, turn.speaker.id, turn.conversation.group_id)
        if turn.conversation.group_id
        else directory(turn.uow, turn.speaker.id)
    )
    if not isinstance(command, AnswerPrompt | Unknown | Acknowledge | Help):
        drop_stale_prompts(turn)
    match command:
        case StartSplit() if photo is not None:
            add_photo(turn, photo, _who_for_photo(turn, command, people))
        case StartSplit():
            turn.reply("Send the receipt photo with that message.")
        case AddManualBill():
            _manual_bill(turn, command, people)
        case AnswerPrompt():
            handle_answer(turn, command, people, rerun=dispatch)
        case Edit(op, None, _):
            _edit_draft(turn, op, people)
        case ConfirmDraft():
            confirm(turn, _draft_under_review(turn))
        case CancelDraft():
            cancel(turn, _open_draft(turn))
        case ShowBillDetails(target):
            details(turn, target)
        case FileIntoGroup(name):
            _file_into_group(turn, name)
        case _:
            route(turn, command, people)


STALE_WHEN_IGNORED = frozenset(
    {PromptKind.WHICH_PERSON, PromptKind.NEED_CONTACT, PromptKind.CONFIRM_ACTION}
)


def drop_stale_prompts(turn: Turn) -> None:
    """A new command means the speaker moved on: their unanswered "which Sam?", contact
    request or restated action is dropped, so it can't catch a later "yes" or number."""
    for prompt in answerable(turn):
        if prompt.kind in STALE_WHEN_IGNORED and prompt.asked_of == turn.speaker.id:
            drop(turn, prompt)


def _may_act_here(turn: Turn, command: Command) -> bool:
    """Non-members can join, ask for help, or answer their own "join splits here?"; people
    who left can still ask for balances."""
    group_id = turn.conversation.group_id or ""
    if turn.speaker.id in current_member_ids(turn.uow, group_id):
        return True
    if isinstance(command, JoinGroup | Help | Unknown | Acknowledge):
        return True
    was_member = any(
        m.person_id == turn.speaker.id for m in turn.uow.memberships.for_group(group_id)
    )
    if was_member and isinstance(command, ShowBalances):
        return True  # a leaver's balance stays, and they can still see it (B2)
    return isinstance(command, AnswerPrompt) and any(
        p.kind is PromptKind.JOIN_GROUP for p in answerable(turn)
    )


def _who_for_photo(turn: Turn, command: StartSplit, people: Directory) -> Who | None:
    if turn.in_group:
        return who_for_group(
            turn,
            people,
            people=command.people,
            everyone=command.everyone,
            excluding=command.excluding,
            payer=command.payer,
            owes_all=command.owes_all,
        )
    if not command.people:
        return None
    return who_for_personal(
        turn, people, people=command.people, payer=command.payer, owes_all=command.owes_all
    )


def _manual_bill(turn: Turn, command: AddManualBill, people: Directory) -> None:
    """ "electricity 1800, split all": one line, reviewed like a receipt (C4)."""
    current = active_draft(turn)
    if current is not None:
        raise NotAllowedError(f"Let's finish the {current.description} bill first.")
    if turn.in_group:
        who: Who | None = who_for_group(
            turn,
            people,
            people=command.people,
            everyone=command.everyone,
            excluding=command.excluding,
            payer=command.payer,
            owes_all=command.owes_all,
        )
    elif command.people or command.exact:
        named = command.people or tuple(e.person for e in command.exact)
        who = who_for_personal(
            turn, people, people=named, payer=command.payer, owes_all=command.owes_all
        )
    else:
        who = None
    line = manual_line(turn, command.description, command.amount)
    overrides: tuple[tuple[str, Override], ...] = ()
    if command.exact and who is not None:
        region = turn.settings.default_region
        overrides = (
            (
                line.id,
                exact_override(people, region, line.amount_cents, command.exact, who.participants),
            ),
        )
    draft = new_draft(
        turn,
        context=GroupContext(turn.conversation.group_id)
        if turn.conversation.group_id
        else PersonalContext(),
        who=who or Who((turn.speaker.id,), turn.speaker.id, None),
        description=command.description,
        lines=(line,),
        totals=(0, 0, command.amount),
        state=DraftState.REVIEWING if who else DraftState.AWAITING_PEOPLE,
        purchased_at=command.purchased_on,
        overrides=overrides,
    )
    if who is None:
        ask_who_with(turn, draft)
    else:
        turn.reply(present(turn, draft))


def _edit_draft(turn: Turn, op: EditOp, people: Directory) -> None:
    """Anyone in the chat may fix the draft under review; only the adder saves it. With no
    draft, an edit is for the one bill just listed here (a reply to its message)."""
    draft = active_draft(turn)
    if draft is None or draft.state is not DraftState.REVIEWING:
        try:
            bill = find_bill(turn, None)
        except NotAllowedError:
            raise NotAllowedError("There's no bill under review here.") from None
        propose_edit(turn, Edit(op, None), bill, op, directory=people, reason=None)
        return
    changed = apply_edit(turn, draft, op, people)
    turn.reply(present(turn, save(turn, draft, changed)))


def _draft_under_review(turn: Turn) -> BillDraft:
    draft = active_draft(turn)
    if draft is None or draft.state is not DraftState.REVIEWING:
        raise NotAllowedError("There's no bill under review here.")
    return draft


def _open_draft(turn: Turn) -> BillDraft:
    draft = active_draft(turn)
    if draft is None:
        raise NotAllowedError("There's no bill to cancel here.")
    return draft


def _viewer(turn: Turn) -> str | None:
    return None if turn.in_group else turn.speaker.id


def _file_into_group(turn: Turn, name: str) -> None:
    """ "add to Flat 4B" from a personal chat: the group's rules apply, questions are asked
    here, the adder confirms here, and the saved bill is posted in the group (D5)."""
    if turn.in_group:
        raise NotAllowedError("That's for bills in your own chat with me.")
    draft = _draft_under_review(turn)
    group = next(
        (
            g
            for m in turn.uow.memberships.for_person(turn.speaker.id)
            if m.left_at is None
            and (g := turn.uow.groups.get(m.group_id)) is not None
            and g.name.casefold() == name.strip().casefold()
        ),
        None,
    )
    if group is None:
        raise NotAllowedError(f"You're not in a group called {name}.")
    members = current_member_ids(turn.uow, group.id)
    named = [p for p in draft.participants if p != turn.speaker.id]
    if any(p not in members for p in named):
        raise NotAllowedError(f"Everyone in this bill has to be in {group.name}.")
    participants = tuple(draft.participants) if named else tuple(members)
    filed = replace(draft, context=GroupContext(group.id), participants=participants)
    turn.reply(present(turn, save(turn, draft, filed)))

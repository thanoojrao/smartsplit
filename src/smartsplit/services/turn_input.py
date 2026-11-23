"""What the model sees for one turn, as data (SPEC 8.2).

`<state>` is a compact snapshot built fresh from the database, `<recent_chat>` the last few
messages of this chat with what each bot message showed, `<message>` the new message.
Handles are issued in the order things appear. In a group chat nothing from another context
is included (SPEC 10.7). All chat text is untrusted, so it is escaped inside its tags.
"""

from collections.abc import Sequence
from html import escape
from zoneinfo import ZoneInfo

from smartsplit.domain.enums import DraftState, PhotoOutcome, PromptStatus
from smartsplit.domain.messages import InboundMessage
from smartsplit.domain.model import BillDraft, PhotoRead
from smartsplit.domain.prompts import ChatMessage, ChatRef, PendingActionPayload
from smartsplit.ports.repository import OPEN_DRAFT_STATES
from smartsplit.services.drafting import open_questions, split_of
from smartsplit.services.names import known_people
from smartsplit.services.pending import open_actions
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.summary import Renderer
from smartsplit.services.text import money, name_for
from smartsplit.services.turn import Turn

RECENT_PEOPLE = 20
FULL_LINES_UP_TO = 15


def build_turn_input(
    turn: Turn, message: InboundMessage, photo: PhotoRead | None, welcomed: bool
) -> str:
    """The turn's user message: state, recent chat and the new message, each in its tag."""
    turn.handles.speaker_id = turn.speaker.id
    state = _state(turn, welcomed)
    chat = _recent_chat(turn)
    said = _message(turn, message, photo)
    return (
        f"<state>\n{state}\n</state>\n"
        f"<recent_chat>\n{chat}\n</recent_chat>\n"
        f"<message>\n{said}\n</message>"
    )


def _text(value: str) -> str:
    return escape(value, quote=False)


def _person(turn: Turn, person_id: str) -> str:
    name = name_for(turn.uow, turn.viewer, person_id)
    return f"{turn.handles.issue('person', person_id, name)} {_text(name)}"


def _state(turn: Turn, welcomed: bool) -> str:
    uow = turn.uow
    lines: list[str] = []
    group_id = turn.conversation.group_id
    if group_id is not None:
        group = uow.groups.get(group_id)
        name = group.name if group else "this group"
        handle = turn.handles.issue("group", group_id, name)
        lines.append(f"chat: group {handle} {_text(name)}")
    else:
        lines.append("chat: personal chat with the speaker")
    lines.append(f"today: {turn.today.isoformat()}")
    lines.append(f'speaker: {_person(turn, turn.speaker.id)} ("me")')
    if welcomed:
        lines.append("the welcome message was just shown to them")
    lines += _people(turn)
    lines += _groups(turn)
    lines += _drafts(turn)
    lines += _actions(turn)
    return "\n".join(lines)


def _people(turn: Turn) -> list[str]:
    uow = turn.uow
    group_id = turn.conversation.group_id
    if group_id is not None:
        current = set(current_member_ids(uow, group_id))
        ever = list(dict.fromkeys(m.person_id for m in uow.memberships.for_group(group_id)))
        rows = [f"{_person(turn, p)}{'' if p in current else ' (left the group)'}" for p in ever]
        if turn.speaker.id not in current:
            rows.append("(the speaker isn't a member of this group)")
        return ["people in this group:", *rows]
    recent = [p for p in known_people(uow, turn.speaker.id) if p != turn.speaker.id]
    return ["people the speaker knows (find_person finds others):"] + [
        _person(turn, p) for p in recent[:RECENT_PEOPLE]
    ]


def _groups(turn: Turn) -> list[str]:
    if turn.in_group:
        return []
    rows = []
    for membership in turn.uow.memberships.for_person(turn.speaker.id):
        group = turn.uow.groups.get(membership.group_id)
        if membership.left_at is None and group is not None:
            rows.append(f"{turn.handles.issue('group', group.id, group.name)} {_text(group.name)}")
    return ["the speaker's groups:", *rows] if rows else []


def _drafts(turn: Turn) -> list[str]:
    drafts = turn.uow.drafts.for_conversation(turn.conversation.key, OPEN_DRAFT_STATES)
    rows: list[str] = []
    for draft in drafts:
        if draft.state is DraftState.QUEUED:
            continue
        rows += _draft(turn, draft)
    queued = [d for d in drafts if d.state is DraftState.QUEUED]
    if queued:
        rows.append(f"queued bills (start when the adder's current one is done): {len(queued)}")
    return ["bills being added here:", *rows] if rows else ["no bills being added here"]


def _draft(turn: Turn, draft: BillDraft) -> list[str]:
    currency = turn.settings.currency
    handle = turn.handles.issue("draft", draft.id, draft.description)
    head = (
        f'{handle} "{_text(draft.description)}", added by {_person(turn, draft.added_by)}, '
        f"{draft.state.value.replace('_', ' ')}, version {draft.version}"
    )
    rows = [head]
    if draft.waiting_for:
        rows.append(f"  names not found yet: {_text(', '.join(draft.waiting_for))}")
    rows.append(f"  paid by {_person(turn, draft.payer_id)}")
    if draft.state is not DraftState.REVIEWING:
        rows.append(f"  people so far: {', '.join(_person(turn, p) for p in draft.participants)}")
        return rows
    split = split_of(turn, draft)
    rows.append(
        "  shares: "
        + ", ".join(
            f"{_person(turn, p)} {money(c, currency)}" for p, c in split.result.shares.items()
        )
    )
    rows.append(f"  total {money(draft.total_cents, currency)}")
    if split.difference_cents:
        rows.append(f"  lines differ from the total by {money(split.difference_cents, currency)}")
    if draft.possible_duplicate_of is not None:
        rows.append("  possible duplicate of another bill: saving needs keep_duplicate")
    flagged = [
        f"L{x.position}" for x in draft.lines if x.confidence < turn.settings.min_line_confidence
    ]
    if flagged:
        rows.append(f"  unclear lines: {', '.join(flagged)}")
    renderer = Renderer(turn.uow, turn.viewer, currency)
    for question in open_questions(turn, draft):
        text = renderer.questions(draft, [question])
        if text:
            q = turn.handles.issue("question", question.id, "that question")
            rows.append(f"  open question {q}: {_text(text[0])}")
    if len(draft.lines) <= FULL_LINES_UP_TO:
        who = {a.item_id: a.member_ids for a in split.result.assignments}
        rows += [
            f"  L{x.position} {_text(x.name)} {money(x.amount_cents, currency)}: "
            + ", ".join(
                turn.handles.issue("person", p, name_for(turn.uow, turn.viewer, p))
                for p in who.get(x.id, ())
            )
            for x in draft.lines
        ]
    else:
        rows.append(f"  {len(draft.lines)} lines (get_bill shows them)")
    return rows


def _actions(turn: Turn) -> list[str]:
    zone = ZoneInfo(turn.settings.timezone)
    rows = []
    for prompt in open_actions(turn):
        payload = prompt.payload
        if not isinstance(payload, PendingActionPayload) or prompt.status is not PromptStatus.OPEN:
            continue
        handle = turn.handles.issue("action", prompt.id, "that")
        until = prompt.expires_at.astimezone(zone).strftime("%H:%M") if prompt.expires_at else ""
        asked = _person(turn, prompt.asked_of or "")
        rows.append(f"{handle} {payload.tool}, waiting for a yes from {asked} until {until}")
    return ["pending actions here:", *rows] if rows else []


def _recent_chat(turn: Turn) -> str:
    messages = turn.uow.chat.recent(turn.conversation.key, turn.settings.chat_history_messages)
    return "\n".join(_line(turn, m) for m in messages) or "(nothing yet)"


def _line(turn: Turn, message: ChatMessage) -> str:
    at = message.created_at.astimezone(ZoneInfo(turn.settings.timezone)).strftime("%H:%M")
    if message.sender_id is not None:
        return f"[{at}] {_person(turn, message.sender_id)}: {_text(message.text)}"
    shown = _refs(turn, message.refs)
    return f"[{at}] bot{f' (showed {shown})' if shown else ''}: {_text(message.text)}"


def _refs(turn: Turn, refs: Sequence[ChatRef]) -> str:
    out: list[str] = []
    for ref in refs:
        label = _ref_label(turn, ref)
        if label is not None:
            handle = turn.handles.issue(ref.kind, ref.id, label)
            out.append(f"{handle} v{ref.version}" if ref.version is not None else handle)
    return ", ".join(out)


def _ref_label(turn: Turn, ref: ChatRef) -> str | None:
    """How a referenced thing reads in a reply; None if it no longer exists."""
    uow = turn.uow
    match ref.kind:
        case "person":
            return name_for(uow, turn.viewer, ref.id) if uow.people.get(ref.id) else None
        case "bill":
            bill = uow.bills.get(ref.id)
            return bill.description if bill else None
        case "draft":
            draft = uow.drafts.get(ref.id)
            return draft.description if draft else None
        case "group":
            group = uow.groups.get(ref.id)
            return group.name if group else None
        case "question" | "action":
            return "that"
        case "payment" | "line":
            return "the payment" if ref.kind == "payment" else "that line"


def _message(turn: Turn, message: InboundMessage, photo: PhotoRead | None) -> str:
    parts = [f"{_person(turn, turn.speaker.id)}: {_text(message.text or '')}"]
    if message.image is not None:
        parts.append(_photo_note(turn, photo))
    if message.contact is not None:
        parts.append(f"[contact card: {_text(message.contact.name)}]")
    return "\n".join(parts)


def _photo_note(turn: Turn, photo: PhotoRead | None) -> str:
    if photo is None:
        return "[photo: not read]"
    if photo.outcome is PhotoOutcome.NOT_A_RECEIPT:
        return "[photo: not a receipt]"
    receipt = turn.uow.receipts.get(photo.receipt_id or "")
    if photo.outcome is PhotoOutcome.UNREADABLE or receipt is None:
        return "[photo: couldn't read it]"
    total = money(receipt.total_cents, turn.settings.currency)
    shop = _text(receipt.merchant or "a shop")
    used = ", already used for a bill" if photo.used_by_draft_id else ""
    return f"[photo: receipt, {shop}, {total}, {len(receipt.line_items)} lines{used}]"

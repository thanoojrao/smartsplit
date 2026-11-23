"""Replies to what the bot asked: which prompt an answer is for, and what it does (SPEC 10.4).

A bare "yes" is a confirm when only line questions are open (the adder can save with questions
still open, G4). Any other open prompt (a duplicate warning, a restated action, "who's this
with?") is a direct question and takes the answer first, newest first.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace

from smartsplit.domain import normalize_item_name
from smartsplit.domain.commands import AnswerPrompt, Command
from smartsplit.domain.enums import DraftState, PromptKind, PromptStatus
from smartsplit.domain.model import BillDraft, Nickname
from smartsplit.domain.phone import mask_phone
from smartsplit.domain.prompts import (
    ConfirmActionPayload,
    NeedContactPayload,
    Prompt,
    RuleChangeEffect,
    StoredImage,
    WhichPersonPayload,
)
from smartsplit.services.drafting import active_draft, present, split_of
from smartsplit.services.errors import NeedsClarificationError, NotAllowedError
from smartsplit.services.lifecycle import finish, start_next
from smartsplit.services.membership import join, person_with_phone
from smartsplit.services.names import Directory
from smartsplit.services.prompting import mark_answered, open_prompt
from smartsplit.services.receipt_flow import answer_who_with
from smartsplit.services.review import answer_question, save
from smartsplit.services.rules_chat import apply_rule_change
from smartsplit.services.saving import confirm, save_bill
from smartsplit.services.text import name_for
from smartsplit.services.turn import Turn

type Rerun = Callable[[Turn, Command, StoredImage | None], None]
"""Handles a command again once the person it named is known."""


def answerable(turn: Turn) -> list[Prompt]:
    """Open prompts in this chat that the speaker may answer, oldest first."""
    return [
        p
        for p in turn.uow.prompts.for_conversation(turn.conversation.key, [PromptStatus.OPEN])
        if p.asked_of in (None, turn.speaker.id)
    ]


TAKES_ANY_ANSWER = frozenset(
    {PromptKind.WHO_WITH, PromptKind.WHICH_PERSON, PromptKind.NEED_CONTACT}
)
"""Prompts whose answer is a number, names or a phone number rather than yes or no."""


def handle_answer(turn: Turn, answer: AnswerPrompt, directory: Directory, rerun: Rerun) -> None:
    prompts = answerable(turn)
    direct = [p for p in prompts if p.kind is not PromptKind.ENGINE_QUESTION]
    questions = [p for p in prompts if p.kind is PromptKind.ENGINE_QUESTION]
    plain = answer.choice is None and not answer.people and not answer.excluding
    if direct and (direct[-1].kind in TAKES_ANY_ANSWER or plain or not questions):
        _answer_direct(turn, direct[-1], answer, directory, rerun)
        return
    if answer.yes is True and plain:
        draft = active_draft(turn)
        if draft is None or draft.state is not DraftState.REVIEWING:
            _aside(turn, "There's nothing to save right now.")
            return
        confirm(turn, draft)
        return
    if not questions:
        _aside(turn, "OK." if answer.yes is False else "I wasn't asking anything.")
        return
    _answer_question(turn, questions, answer, directory)


def _aside(turn: Turn, text: str) -> None:
    """A reply to something that answered nothing; silent for unaddressed group chatter."""
    if turn.addressed:
        turn.reply(text)


def _answer_question(
    turn: Turn, questions: Sequence[Prompt], answer: AnswerPrompt, directory: Directory
) -> None:
    """ "2 no" or "1: Sam and Raj" picks the question by its number in the batch; otherwise
    the first one still unanswered."""
    unanswered = [n for n, q in enumerate(questions, 1) if not q.answers]
    n = answer.choice or (unanswered[0] if unanswered else 1)
    if not 1 <= n <= len(questions):
        raise NotAllowedError(f"There are only {len(questions)} questions open.")
    prompt = questions[n - 1]
    draft = turn.uow.drafts.get(prompt.draft_id or "")
    if draft is None:
        raise NotAllowedError("That bill is gone.")
    changed = answer_question(turn, draft, prompt, answer, directory)
    turn.reply(present(turn, save(turn, draft, changed)))


def _answer_direct(
    turn: Turn, prompt: Prompt, answer: AnswerPrompt, directory: Directory, rerun: Rerun
) -> None:
    payload = prompt.payload
    match prompt.kind:
        case PromptKind.WHO_WITH:
            draft = _draft_of(turn, prompt)
            answer_who_with(turn, draft, prompt, answer, directory)
        case PromptKind.WHICH_PERSON if isinstance(payload, WhichPersonPayload):
            _which_person(turn, prompt, payload, answer, rerun)
        case PromptKind.NEED_CONTACT if isinstance(payload, NeedContactPayload):
            _need_contact(turn, prompt, payload, answer, rerun)
        case PromptKind.JOIN_GROUP:
            mark_answered(turn, prompt, answer)
            if answer.yes:
                join(turn)
        case _ if answer.yes is None:
            raise NotAllowedError('Say "yes" or "no".')
        case PromptKind.CONFIRM_TOTAL:
            _confirm_total(turn, prompt, answer)
        case PromptKind.DUPLICATE_WARNING:
            _duplicate(turn, prompt, answer)
        case PromptKind.CONFIRM_ACTION if isinstance(payload, ConfirmActionPayload):
            mark_answered(turn, prompt, answer)
            if not answer.yes:
                turn.reply("OK, nothing changed.")
            elif isinstance(payload.effect, RuleChangeEffect):
                apply_rule_change(turn, payload.effect)
        case _:
            raise NotAllowedError("I can't use that answer.")


def _draft_of(turn: Turn, prompt: Prompt) -> BillDraft:
    draft = turn.uow.drafts.get(prompt.draft_id or "")
    if draft is None or draft.state not in (DraftState.REVIEWING, DraftState.AWAITING_PEOPLE):
        raise NotAllowedError("That bill isn't open any more.")
    return draft


def _confirm_total(turn: Turn, prompt: Prompt, answer: AnswerPrompt) -> None:
    """ "yes": the difference is shared like a tip, and the bill is saved (C5)."""
    draft = _draft_of(turn, prompt)
    mark_answered(turn, prompt, answer)
    if not answer.yes:
        turn.reply("OK, fix a line or the total, then say yes.")
        return
    difference = split_of(turn, draft).difference_cents
    accepted = replace(
        draft, accepted_difference_cents=draft.accepted_difference_cents + difference
    )
    changed = save(turn, draft, accepted)
    save_bill(turn, changed, split_of(turn, changed))


def _duplicate(turn: Turn, prompt: Prompt, answer: AnswerPrompt) -> None:
    draft = _draft_of(turn, prompt)
    mark_answered(turn, prompt, answer)
    if answer.yes:
        turn.reply(present(turn, draft))
        return
    finish(turn, draft, DraftState.CANCELLED)
    turn.reply(f"OK, dropped the {draft.description} bill.")
    start_next(turn, draft)


def _which_person(
    turn: Turn, prompt: Prompt, payload: WhichPersonPayload, answer: AnswerPrompt, rerun: Rerun
) -> None:
    """The choice becomes the speaker's nickname for that name, so it's never asked again."""
    n = answer.choice
    if n is None or not 1 <= n <= len(payload.candidate_ids):
        raise NotAllowedError(f"Pick a number from 1 to {len(payload.candidate_ids)}.")
    chosen = payload.candidate_ids[n - 1]
    _remember(turn, prompt, answer, chosen, payload.said)
    resume(turn, payload.pending, payload.image, rerun)


def _need_contact(
    turn: Turn, prompt: Prompt, payload: NeedContactPayload, answer: AnswerPrompt, rerun: Rerun
) -> None:
    """A contact card or a number for someone the bot doesn't know yet (A11)."""
    if not answer.text:
        raise NotAllowedError(f"Send {payload.said}'s contact card or phone number.")
    person = person_with_phone(turn, payload.said, answer.text)
    _remember(turn, prompt, answer, person.id, payload.said)
    resume(turn, payload.pending, payload.image, rerun)


def _remember(turn: Turn, prompt: Prompt, answer: AnswerPrompt, person_id: str, said: str) -> None:
    mark_answered(turn, prompt, answer)
    key = normalize_item_name(said)
    if key and person_id != turn.speaker.id:
        turn.uow.nicknames.put(Nickname(turn.speaker.id, person_id, key))


def resume(turn: Turn, pending: Command, image: StoredImage | None, rerun: Rerun) -> None:
    """Run the command that was waiting; a further unknown name is asked about in turn."""
    try:
        rerun(turn, pending, image)
    except NeedsClarificationError as unclear:
        ask_who(turn, unclear, pending, image)


def ask_who(
    turn: Turn, unclear: NeedsClarificationError, pending: Command, image: StoredImage | None
) -> None:
    """ "Which Sam?" with a numbered list, or a request for a contact card."""
    if not unclear.candidate_ids:
        payload_contact = NeedContactPayload(unclear.said, pending, image)
        open_prompt(turn, None, PromptKind.NEED_CONTACT, payload_contact, turn.speaker.id)
        turn.reply(f"I don't know {unclear.said} yet. Send their contact card or number.")
        return
    payload = WhichPersonPayload(unclear.said, unclear.candidate_ids, pending, image)
    open_prompt(turn, None, PromptKind.WHICH_PERSON, payload, turn.speaker.id)
    options = [
        f"{n}. {_label(turn, person_id)}" for n, person_id in enumerate(unclear.candidate_ids, 1)
    ]
    turn.reply("\n".join([f"Which {unclear.said}?", *options]))


def _label(turn: Turn, person_id: str) -> str:
    person = turn.uow.people.get(person_id)
    if person is None:
        return "someone"
    viewer = None if turn.in_group else turn.speaker.id
    return f"{name_for(turn.uow, viewer, person_id)} ({mask_phone(person.phone)})"

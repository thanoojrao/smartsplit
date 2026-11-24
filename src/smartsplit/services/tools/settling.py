"""Draft tools that answer, file, save or cancel a draft (SPEC 8.3, 8.4, 10.4)."""

from dataclasses import replace
from typing import Any

from smartsplit.domain.enums import DraftState, PromptStatus, QuestionReason
from smartsplit.domain.model import BillDraft
from smartsplit.domain.prompts import EngineQuestionPayload, PromptAnswer
from smartsplit.domain.tools import (
    AnswerQuestion,
    CancelDraft,
    ConfirmDraft,
    FileIntoGroup,
)
from smartsplit.domain.values import EqualSplit, GroupContext, Weight
from smartsplit.services.bill_start import (
    with_duplicate_check,
)
from smartsplit.services.drafting import (
    change,
    present,
    split_of,
)
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.review import (
    current_assignees,
    with_override,
)
from smartsplit.services.rules import is_current_member
from smartsplit.services.saving import cancel, save_bill
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.text import name_for
from smartsplit.services.tools import refs
from smartsplit.services.tools.registry import Data, Tool
from smartsplit.services.transcript import last_shown_shares, last_shown_version
from smartsplit.services.turn import Turn


def _answer_question(turn: Turn, args: AnswerQuestion) -> Data:
    """An answer changes that line's current split; the latest answer wins (G2, G3)."""
    prompt = refs.question(turn, args.question)
    payload = prompt.payload
    found = turn.uow.drafts.get(prompt.draft_id or "")
    if (
        prompt.status is not PromptStatus.OPEN
        or not isinstance(payload, EngineQuestionPayload)
        or found is None
    ):
        raise NotAllowedError("That question was already settled.")
    found = refs.reviewable(turn, refs.draft_handle(turn, found))
    line = next((x for x in found.lines if x.id == payload.line_id), None)
    if line is None:
        raise NotAllowedError("That line is gone.")
    now_on = current_assignees(turn, found, line.id)
    if (
        payload.reason is QuestionReason.SOFT_RULE
        and payload.member_id
        and args.included is not None
    ):
        keep = {*now_on, payload.member_id} if args.included else set(now_on) - {payload.member_id}
        on_line = tuple(p for p in found.participants if p in keep)
    elif args.people:
        chosen = set(refs.people(turn, args.people))
        if not chosen <= set(found.participants):
            raise NotAllowedError("Add them to the bill first.")
        on_line = tuple(p for p in found.participants if p in chosen)
    else:
        raise NotAllowedError("Say whether they're in, or who shares that line.")
    if not on_line:
        raise NotAllowedError("Someone has to share it.")
    answer = PromptAnswer(turn.speaker.id, tuple(Weight(p, 1) for p in on_line), turn.now)
    turn.uow.prompts.update(
        replace(prompt, status=PromptStatus.ANSWERED, answers=(*prompt.answers, answer))
    )
    shown = change(turn, found, with_override(found, line.id, EqualSplit(on_line)))
    present(turn, shown)
    return {"draft": refs.draft_handle(turn, shown)}


def _file_into_group(turn: Turn, args: FileIntoGroup) -> Data:
    return file_draft(turn, refs.reviewable(turn, args.draft), refs.group(turn, args.group))


def file_draft(turn: Turn, found: BillDraft, group_id: str) -> Data:
    """ "add to Flat 4B" from a personal chat: the group's rules apply, questions are asked
    here, the adder confirms here, and the saved bill is posted in the group (D5)."""
    if turn.in_group:
        raise NotAllowedError("That's for bills in your own chat with me.")
    if not is_current_member(turn.uow, group_id, turn.speaker.id, turn.now):
        raise NotAllowedError("You're not in that group.")
    members = current_member_ids(turn.uow, group_id)
    named = [p for p in found.participants if p != turn.speaker.id]
    group = turn.uow.groups.get(group_id)
    if any(p not in members for p in named):
        raise NotAllowedError(
            f"Everyone in this bill has to be in {group.name if group else 'it'}."
        )
    participants = tuple(found.participants) if named else tuple(members)
    filed = replace(
        found,
        context=GroupContext(group_id),
        participants=participants,
        waiting_for=(),
        state=DraftState.REVIEWING,
    )
    shown = with_duplicate_check(turn, change(turn, found, filed))
    present(turn, shown)
    return {"draft": refs.draft_handle(turn, shown), "state": shown.state.value}


def _confirm_draft(turn: Turn, args: ConfirmDraft) -> Data:
    """Only the adder saves, on a later message than the summary it confirms (SPEC 8.4)."""
    found = refs.draft(turn, args.draft)
    if found.added_by != turn.speaker.id:
        who = name_for(turn.uow, turn.viewer, found.added_by)
        raise NotAllowedError(f"Only {who} can save this bill.")
    if found.state is not DraftState.REVIEWING:
        raise NotAllowedError("That bill isn't ready to save yet.")
    if found.id in turn.changed_drafts:
        return {
            "saved": False,
            "why": "it was just shown or changed: the adder has to see it first",
        }
    if not _seen_as_it_is(turn, found):
        present(turn, found)
        return {
            "saved": False,
            "why": "it changed since the summary the adder said yes to; the new split is shown",
        }
    if found.possible_duplicate_of is not None and not args.keep_duplicate:
        return {"saved": False, "why": "it looks like a duplicate: ask whether to keep it"}
    difference = split_of(turn, found).difference_cents
    if difference and not args.accept_difference:
        return {
            "saved": False,
            "why": "the lines don't add up to the total: fix a line or keep the difference",
        }
    bill = save_bill(turn, found, accept_difference=bool(difference))
    return {"saved": True, "bill": refs.bill_handle(turn, bill)}


def _seen_as_it_is(turn: Turn, found: BillDraft) -> bool:
    """The chat's latest summary shows this version and these shares: a rule made since
    changes the shares without a new version. A "yes" quoting an older summary answers that
    one, not what the bill is now (G4)."""
    key, keep = turn.conversation.key, turn.settings.chat_history_keep
    shares = split_of(turn, found).fingerprint
    if last_shown_version(turn.uow, key, found.id, keep) != found.version:
        return False
    if last_shown_shares(turn.uow, key, found.id, keep) != shares:
        return False
    quoted = [r for r in turn.quoted if r.kind == "draft" and r.id == found.id]
    return all(r.version == found.version and r.shares in (None, shares) for r in quoted)


def _cancel_draft(turn: Turn, args: CancelDraft) -> Data:
    cancel(turn, refs.draft(turn, args.draft))
    return {"cancelled": True}


SAVING_TOOLS: tuple[Tool[Any], ...] = (
    Tool(
        "answer_question",
        'Answer an open question (Q): included true/false for "is X in?", or people for '
        '"who is it for?".',
        AnswerQuestion,
        _answer_question,
    ),
    Tool(
        "file_into_group",
        "File a draft from the speaker's own chat into one of their groups. If they named the "
        "group for a new bill, do it in the same turn the bill is started, before they see it.",
        FileIntoGroup,
        _file_into_group,
    ),
    Tool(
        "confirm_draft",
        "Save a draft the adder has seen and said yes to. Set keep_duplicate or "
        "accept_difference only after they said so.",
        ConfirmDraft,
        _confirm_draft,
    ),
    Tool("cancel_draft", "Cancel a draft; nothing is saved.", CancelDraft, _cancel_draft),
)

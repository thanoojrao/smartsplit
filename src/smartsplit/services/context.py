"""What the interpreter may know about a chat: names and short texts, never ids (SPEC 12.3)."""

from datetime import date

from smartsplit.domain.enums import ConversationKind, PromptKind, PromptStatus
from smartsplit.domain.model import Conversation
from smartsplit.ports.llm import InterpretContext
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.drafting import ACTIVE
from smartsplit.services.names import directory
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.summary import Renderer
from smartsplit.services.text import money, name_for


def interpret_context(
    uow: UnitOfWork,
    *,
    speaker_id: str | None,
    conversation: Conversation | None,
    kind: ConversationKind,
    today: date,
    currency: str,
) -> InterpretContext:
    """Who the speaker can name, the open questions and the bill under review, as text."""
    viewer = speaker_id if kind is ConversationKind.PERSONAL else None
    nameable = directory(uow, speaker_id).people if speaker_id else ()
    group_id = conversation.group_id if conversation else None
    members = current_member_ids(uow, group_id) if group_id else []
    groups = []
    if speaker_id:
        for membership in uow.memberships.for_person(speaker_id):
            group = uow.groups.get(membership.group_id)
            if membership.left_at is None and group is not None:
                groups.append(group.name)
    prompts: list[str] = []
    lines: list[str] = []
    if conversation is not None:
        drafts = uow.drafts.for_conversation(conversation.key, ACTIVE)
        renderer = Renderer(uow, viewer, currency)
        open_prompts = uow.prompts.for_conversation(conversation.key, [PromptStatus.OPEN])
        questions = [p for p in open_prompts if p.kind is PromptKind.ENGINE_QUESTION]
        if drafts:
            prompts += renderer.questions(drafts[0], questions)
            lines += [
                f"{n}. {line.name} {money(line.amount_cents, currency)}"
                for n, line in enumerate(drafts[0].lines, 1)
            ]
        prompts += [
            p.kind.value.replace("_", " ")
            for p in open_prompts
            if p.kind is not PromptKind.ENGINE_QUESTION
        ]
    return InterpretContext(
        conversation_kind=kind,
        conversation_name=conversation.name if conversation else None,
        today=today,
        speaker_id=speaker_id or "",
        nameable=nameable,
        group_member_names=tuple(name_for(uow, viewer, m) for m in members),
        group_names=tuple(groups),
        open_prompts=tuple(prompts),
        draft_lines=tuple(lines),
    )

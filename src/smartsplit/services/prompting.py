"""Opening and answering prompts: what the bot waits for, persisted (SPEC 4.5)."""

from dataclasses import replace

from smartsplit.domain.commands import AnswerPrompt
from smartsplit.domain.enums import PromptKind, PromptStatus
from smartsplit.domain.prompts import Prompt, PromptAnswer, PromptPayload
from smartsplit.services.turn import Turn


def open_prompt(
    turn: Turn,
    draft_id: str | None,
    kind: PromptKind,
    payload: PromptPayload,
    asked_of: str | None,
) -> Prompt:
    """Ask in this chat; `asked_of` None lets anyone in the bill's context answer."""
    prompt = Prompt(
        turn.ids.new_id(),
        turn.conversation.key,
        draft_id,
        kind,
        payload,
        PromptStatus.OPEN,
        asked_of,
        turn.speaker.id,
        turn.now,
        (),
    )
    turn.uow.prompts.add(prompt)
    return prompt


def mark_answered(turn: Turn, prompt: Prompt, answer: AnswerPrompt) -> None:
    """Who answered what is kept on the prompt, so "latest answer wins" is traceable."""
    turn.uow.prompts.update(
        replace(
            prompt,
            status=PromptStatus.ANSWERED,
            answers=(*prompt.answers, PromptAnswer(turn.speaker.id, answer, turn.now)),
        )
    )


def drop(turn: Turn, prompt: Prompt) -> None:
    turn.uow.prompts.update(replace(prompt, status=PromptStatus.DROPPED))

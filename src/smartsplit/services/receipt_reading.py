"""Reading receipts outside the conversation lock, then finishing them under it (SPEC 12.2).

A draft waits in `parsing` while the model reads it; the result is applied only if the draft
is still waiting. Finishing or failing one can start the next queued draft, read in turn.
When the model is down, the chat is told once; `tick` then retries quietly, and gives up on
a receipt still unread after `draft_expires_after`.
"""

from dataclasses import dataclass, replace

from smartsplit.domain.enums import DraftState
from smartsplit.domain.messages import OutboundMessage
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.images import ImageStore
from smartsplit.ports.llm import (
    Canonicalizer,
    LlmUnavailableError,
    ParsedReceipt,
    ReceiptParser,
    ReceiptUnreadableError,
)
from smartsplit.ports.repository import Repository
from smartsplit.ports.system import Clock, IdGenerator
from smartsplit.services.drafting import lines_from_receipt
from smartsplit.services.matching import MatchedLines, load_match_inputs, match_lines
from smartsplit.services.receipt_flow import finish_parse, parse_failed
from smartsplit.services.scopes import local_scope_for
from smartsplit.services.text import READ_LATER
from smartsplit.services.turn import OrchestratorSettings, Turn


@dataclass(frozen=True, slots=True)
class Source:
    """The inbound message that started the reading: its stored replies get the results, so
    a retry of that message returns them too."""

    conversation: ConversationKey
    message_id: str


@dataclass(frozen=True, slots=True)
class ReceiptReader:
    repository: Repository
    images: ImageStore
    parser: ReceiptParser
    canonicalizer: Canonicalizer
    clock: Clock
    ids: IdGenerator
    settings: OrchestratorSettings

    def read_all(self, source: Source | None, draft_ids: list[str]) -> list[OutboundMessage]:
        replies: list[OutboundMessage] = []
        pending = list(draft_ids)
        while pending:
            more_replies, more = self.read(source, pending.pop(0))
            replies += more_replies
            pending += more
        return replies

    def read(self, source: Source | None, draft_id: str) -> tuple[list[OutboundMessage], list[str]]:
        """One draft: the model reads it, then a locked transaction applies the result."""
        with self.repository.unit_of_work() as uow:
            draft = uow.drafts.get(draft_id)
            if draft is None or draft.state is not DraftState.PARSING or not draft.image_ref:
                return [], []
            inputs = load_match_inputs(uow, local_scope_for(draft.context, draft.added_by))
            chat = uow.conversations.get(draft.conversation)
        result: tuple[ParsedReceipt, MatchedLines] | None = None
        outage = False
        try:
            image = self.images.load(draft.image_ref)
            parsed = self.parser.parse(image, draft.image_mime_type or "", self.settings.currency)
            lines = lines_from_receipt(self.ids, parsed)
            matched = match_lines(lines, inputs, self.canonicalizer, self.settings.fuzzy_threshold)
            result = (parsed, matched)
        except (KeyError, ReceiptUnreadableError):
            result = None
        except LlmUnavailableError:
            if source is not None:
                recipient = chat.person_id if chat else None
                return [OutboundMessage(draft.conversation, recipient, READ_LATER)], []
            outage = True
        with self.repository.unit_of_work(lock=draft.conversation) as uow:
            current = uow.drafts.get(draft_id)
            conversation = uow.conversations.get(draft.conversation)
            adder = uow.people.get(draft.added_by)
            if current is None or current.state is not DraftState.PARSING:
                return [], []
            if conversation is None or adder is None:
                return [], []
            turn = Turn(uow, self.ids, self.clock.now(), self.settings, adder, conversation)
            gave_up = turn.now - current.created_at >= self.settings.draft_expires_after
            if outage and not gave_up:
                # a quiet retry: wait a while before the next attempt, say nothing more
                uow.drafts.update(replace(current, last_activity_at=turn.now), DraftState.PARSING)
                return [], []
            if result is None:
                parse_failed(turn, current)
            else:
                parsed, matched = result
                for _ in range(1 + matched.model_calls):
                    uow.llm_usage.increment(adder.id, turn.today)
                finish_parse(turn, current, parsed, matched)
            if source is not None:
                uow.processed.add_replies(source.conversation, source.message_id, turn.replies)
            return turn.replies, turn.to_parse

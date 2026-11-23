"""What one handled message works with: the unit of work, the speaker, the chat, the replies."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from smartsplit.domain.messages import OutboundMessage
from smartsplit.domain.model import Conversation, Person
from smartsplit.ports.repository import UnitOfWork
from smartsplit.ports.system import IdGenerator


@dataclass(frozen=True, slots=True)
class OrchestratorSettings:
    """The parts of config.Settings the conversation logic needs (injected, SPEC section 2)."""

    currency: str = "INR"
    default_region: str = "IN"
    timezone: str = "Asia/Kolkata"
    fuzzy_threshold: int = 85
    min_line_confidence: float = 0.6
    max_receipt_lines: int = 150
    max_amount_cents: int = 100_000_000
    max_queued_drafts: int = 3
    llm_calls_per_person_per_day: int = 50
    duplicate_window_days: int = 3
    questions_per_message: int = 3
    max_notifications_per_day: int = 20
    invite_template: str = "I added our split on SmartSplit. Say hi to the bot to see it."
    draft_reminder_after: timedelta = timedelta(hours=24)
    draft_expires_after: timedelta = timedelta(days=3)
    remind_once_per: timedelta = timedelta(hours=24)
    notifications_per_tick: int = 200


@dataclass(slots=True)
class Turn:
    """Collects the replies of one message; messages may go to any chat (SPEC section 2)."""

    uow: UnitOfWork
    ids: IdGenerator
    now: datetime
    settings: OrchestratorSettings
    speaker: Person
    conversation: Conversation
    replies: list[OutboundMessage] = field(default_factory=list)
    addressed: bool = True
    """False for group chatter the bot only read because a question is open (SPEC 10.2)."""
    to_parse: list[str] = field(default_factory=list)
    """Drafts that moved to `parsing` this turn: read after commit, outside the lock (12.2)."""

    @property
    def in_group(self) -> bool:
        return self.conversation.group_id is not None

    @property
    def today(self) -> date:
        """The install's local date: what "this month" and a bill's default date mean."""
        return self.now.astimezone(ZoneInfo(self.settings.timezone)).date()

    def reply(self, text: str) -> None:
        """Answer in this chat."""
        self.replies.append(
            OutboundMessage(self.conversation.key, self.conversation.person_id, text)
        )

    def post(self, conversation: Conversation, text: str) -> None:
        """Post in another chat, e.g. a bill filed into a group from a personal chat."""
        self.replies.append(OutboundMessage(conversation.key, conversation.person_id, text))

    def direct(self, person_id: str, text: str) -> bool:
        """Send to the person's own chat ("sent you a DM"); False if they have none yet."""
        chat = self.uow.conversations.personal_for(person_id)
        if chat is None:
            return False
        self.post(chat, text)
        return True

"""What one handled message (or one `tick` step) works with: the unit of work, the speaker,
the chat, the handles issued so far, and everything the bot says (SPEC 8.1, 8.5, 8.6)."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from smartsplit.domain.messages import ContactAttachment
from smartsplit.domain.model import Conversation, Person
from smartsplit.domain.prompts import ChatRef
from smartsplit.ports.repository import UnitOfWork
from smartsplit.ports.system import IdGenerator
from smartsplit.services.handles import Handles
from smartsplit.services.matching import ItemKeys


@dataclass(frozen=True, slots=True)
class OrchestratorSettings:
    """The parts of config.Settings the conversation logic needs (injected, SPEC section 2)."""

    currency: str = "INR"
    default_region: str = "IN"
    timezone: str = "Asia/Kolkata"
    bot_link: str = "https://wa.me/<bot-number>?text=hi"
    fuzzy_threshold: int = 85
    min_line_confidence: float = 0.6
    max_receipt_lines: int = 150
    max_amount_cents: int = 100_000_000
    max_queued_drafts: int = 3
    llm_calls_per_person_per_day: int = 150
    llm_calls_per_day: int = 3000
    llm_timeout_seconds: float = 30
    message_seconds: float = 60
    lock_wait_seconds: float = 15
    max_image_bytes: int = 5_000_000
    agent_max_steps: int = 6
    chat_history_messages: int = 10
    chat_history_keep: int = 50
    chat_history_days: int = 30
    duplicate_window_days: int = 3
    questions_shown: int = 3
    max_notifications_per_day: int = 20
    draft_reminder_after: timedelta = timedelta(hours=24)
    draft_expires_after: timedelta = timedelta(days=3)
    remind_once_per: timedelta = timedelta(hours=24)
    pending_lasts: timedelta = timedelta(minutes=30)
    photo_pickup_within: timedelta = timedelta(minutes=10)
    notifications_per_tick: int = 200


def local_date(now: datetime, timezone: str) -> date:
    """The install's day: what daily limits and "this month" count by."""
    return now.astimezone(ZoneInfo(timezone)).date()


@dataclass(frozen=True, slots=True)
class Said:
    """One message the bot sends, with what it showed (stored in that chat's transcript)."""

    conversation: Conversation
    text: str
    refs: tuple[ChatRef, ...] = ()
    stored: str | None = None
    """What the transcript keeps, if not the compacted text (the model's own words are kept
    whole; only code-rendered blocks are shortened)."""
    summary_of: str | None = None
    """The draft this block is the review summary of: a later summary of it replaces it."""


@dataclass(slots=True)
class Turn:
    """Collects what the bot says during one message; messages may go to any chat (SPEC 2)."""

    uow: UnitOfWork
    ids: IdGenerator
    now: datetime
    settings: OrchestratorSettings
    speaker: Person
    conversation: Conversation
    message_id: str = ""
    contact: ContactAttachment | None = None
    """A contact card that came with this message."""
    canonicalizer: ItemKeys | None = None
    """Item names for receipt lines; counted and never failing the turn (SPEC 8.7)."""
    quoted: tuple[ChatRef, ...] = ()
    """What the bot message this one replies to showed (SPEC 8.6)."""
    handles: Handles = field(default_factory=Handles)
    shown: list[Said] = field(default_factory=list)
    """Blocks rendered by code for this chat, appended to the model's reply as they are."""
    elsewhere: list[Said] = field(default_factory=list)
    """Group posts and DMs to other chats."""
    changed_drafts: set[str] = field(default_factory=set)
    """Drafts created or changed this turn: the adder must see them before saving (8.4)."""
    acted: bool = False
    """A tool changed something this turn."""

    @property
    def in_group(self) -> bool:
        return self.conversation.group_id is not None

    @property
    def today(self) -> date:
        """The install's local date: what "this month" and a bill's default date mean."""
        return local_date(self.now, self.settings.timezone)

    @property
    def viewer(self) -> str | None:
        """Whose names to use: the speaker's own in a personal chat, display names in a group."""
        return None if self.in_group else self.speaker.id

    def show(
        self, text: str, refs: tuple[ChatRef, ...] = (), *, summary_of: str | None = None
    ) -> None:
        """A block for this chat, rendered by code."""
        self.shown.append(Said(self.conversation, text, refs, summary_of=summary_of))

    def post(
        self,
        conversation: Conversation,
        text: str,
        refs: tuple[ChatRef, ...] = (),
        *,
        summary_of: str | None = None,
    ) -> None:
        """Say it in the given chat: this one, or another (a group post, a DM)."""
        if conversation.key == self.conversation.key:
            self.show(text, refs, summary_of=summary_of)
        else:
            self.elsewhere.append(Said(conversation, text, refs, summary_of=summary_of))

    def direct(self, person_id: str, text: str, refs: tuple[ChatRef, ...] = ()) -> bool:
        """Send to the person's own chat ("sent you a DM"); False if they have none yet."""
        chat = self.uow.conversations.personal_for(person_id)
        if chat is None:
            return False
        self.post(chat, text, refs)
        return True

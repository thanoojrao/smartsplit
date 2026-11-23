"""A whole bot on the in-memory fakes, and people who talk to it (SPEC section 10 tests)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

from smartsplit.adapters.fakes.images import InMemoryImageStore
from smartsplit.adapters.fakes.interpreter import KeywordInterpreter
from smartsplit.adapters.fakes.llm import FakeCanonicalizer, FakeReceiptParser
from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.adapters.fakes.system import FixedClock, SequentialIds
from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.messages import (
    ChatEvent,
    ContactAttachment,
    ImageAttachment,
    InboundMessage,
    OutboundMessage,
)
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.llm import CommandInterpreter
from smartsplit.ports.repository import Repository
from smartsplit.services.orchestrator import Orchestrator
from smartsplit.services.turn import OrchestratorSettings

T0 = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
RECEIPTS = Path(__file__).parent.parent / "fixtures" / "receipts"


def receipt(name: str) -> ImageAttachment:
    """A recorded receipt, which the fake parser reads like a photo."""
    return ImageAttachment("image/jpeg", (RECEIPTS / f"{name}.json").read_bytes())


@dataclass(frozen=True, slots=True)
class Someone:
    name: str
    phone: str

    @property
    def ref(self) -> str:
        return self.phone


YOU = Someone("Thanoo", "+919876500001")
SAM = Someone("Sam", "+919876500002")
RAJ = Someone("Raj", "+919876500003")
PRIYA = Someone("Priya", "+919876500004")


@dataclass
class World:
    """One bot; `say` sends a message and returns the texts that came back, by chat."""

    clock: FixedClock = field(default_factory=lambda: FixedClock(T0))
    repository: Repository = field(default_factory=InMemoryRepository)
    canonical: FakeCanonicalizer = field(default_factory=FakeCanonicalizer)
    interpreter: CommandInterpreter | None = None
    """None: the keyword fake, which canonicalizes with `canonical`."""
    settings: OrchestratorSettings = field(default_factory=OrchestratorSettings)
    last: list[OutboundMessage] = field(default_factory=list)
    _ids: "count[int]" = field(default_factory=count)

    def __post_init__(self) -> None:
        ids = SequentialIds()
        self.parser = FakeReceiptParser(self.settings.max_receipt_lines)
        self.interpreter = self.interpreter or KeywordInterpreter(self.canonical)
        self.bot = Orchestrator(
            repository=self.repository,
            images=InMemoryImageStore(self.clock, SequentialIds("img")),
            parser=self.parser,
            interpreter=self.interpreter,
            clock=self.clock,
            ids=ids,
            settings=self.settings,
        )

    def message(
        self,
        who: Someone,
        chat: str | None = None,
        text: str | None = None,
        *,
        image: ImageAttachment | None = None,
        contact: ContactAttachment | None = None,
        event: ChatEvent | None = None,
        addressed: bool = True,
        message_id: str | None = None,
    ) -> InboundMessage:
        group = chat is not None
        return InboundMessage(
            message_id=message_id or f"m{next(self._ids)}",
            conversation=ConversationKey("test", chat or f"dm:{who.phone}"),
            conversation_kind=ConversationKind.GROUP if group else ConversationKind.PERSONAL,
            conversation_name=chat,
            sender_ref=who.ref,
            sender_alt_ref=None,
            sender_phone=who.phone,
            sender_name=who.name,
            addressed_to_bot=addressed and group,
            reply_to_bot=False,
            text=text,
            image=image,
            contact=contact,
            event=event,
        )

    def send(self, message: InboundMessage) -> str:
        self.last = self.bot.handle(message)
        return "\n".join(m.text for m in self.last)

    def say(
        self,
        who: Someone,
        chat: str | None,
        text: str | None = None,
        *,
        image: ImageAttachment | None = None,
        contact: ContactAttachment | None = None,
        addressed: bool = True,
    ) -> str:
        """All reply texts, joined; `chat` None is the speaker's personal chat."""
        message = self.message(who, chat, text, image=image, contact=contact, addressed=addressed)
        return self.send(message)

    def in_chat(self, chat: str | None, who: Someone | None = None) -> str:
        """Only the texts of the last replies that went to one chat."""
        ref = chat if chat is not None else f"dm:{who.phone if who else ''}"
        return "\n".join(m.text for m in self.last if m.conversation.ref == ref)


FLAT = "Flat 4B"


def flat(world: World, *people: Someone) -> None:
    """Flat 4B with these people in it, everyone having used the bot 1:1 first."""
    for person in people:
        world.say(person, None, "help")
    first, *rest = people
    world.say(first, FLAT, "help")
    for person in rest:
        world.say(person, FLAT, "join")

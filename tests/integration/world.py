"""A whole bot on the in-memory fakes, and people who talk to it (SPEC section 10 tests).

The model is a `ScriptedAgent`: each `say` queues the steps the model takes for that message,
so tests drive the real tools and check state, shown blocks and transcripts (SPEC 8.7).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

from smartsplit.adapters.fakes.agent import ScriptedAgent, Step, call, first_handle, handle_of
from smartsplit.adapters.fakes.images import InMemoryImageStore
from smartsplit.adapters.fakes.llm import FakeCanonicalizer, FakeReceiptParser
from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.adapters.fakes.system import FixedClock, SequentialIds
from smartsplit.domain.enums import ConversationKind, DraftState
from smartsplit.domain.messages import (
    ChatEvent,
    ContactAttachment,
    ImageAttachment,
    InboundMessage,
    Mention,
    OutboundMessage,
)
from smartsplit.domain.model import BillDraft, Person
from smartsplit.domain.prompts import ChatMessage
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.agent import AgentModel, AgentRequest, ModelStep
from smartsplit.ports.llm import ReceiptParser
from smartsplit.ports.repository import Repository
from smartsplit.services.orchestrator import Orchestrator
from smartsplit.services.outcomes import HandleOutcome
from smartsplit.services.turn import OrchestratorSettings, local_date

T0 = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
_MESSAGE_IDS = count()
"""Shared by every World, so two bots on one database never reuse a message id."""
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


YOU = Someone("Alex", "+919876500001")
SAM = Someone("Sam", "+919876500002")
RAJ = Someone("Raj", "+919876500003")
PRIYA = Someone("Priya", "+919876500004")
FLAT = "Flat 4B"


def calling(tool: str, /, **arguments: object) -> Step:
    """A tool call whose arguments may name people as `"@Sam"` (→ Sam's handle this turn),
    drafts as `"@D"` (→ the first draft handle), actions as `"@A"`, bills as `"@B"`."""

    def step(request: AgentRequest) -> ModelStep:
        return call(tool, **{k: _resolve(request, v) for k, v in arguments.items()})

    return step


def _resolve(request: AgentRequest, value: object) -> object:
    if isinstance(value, str) and value.startswith("@"):
        wanted = value[1:]
        if wanted in {"D", "A", "B", "Q", "G", "T"}:
            return first_handle(request, wanted)
        return handle_of(request, wanted)
    if isinstance(value, list | tuple):
        return [_resolve(request, v) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(request, v) for k, v in value.items()}
    return value


@dataclass
class World:
    """One bot; `say` sends a message and returns the texts that came back, by chat."""

    clock: FixedClock = field(default_factory=lambda: FixedClock(T0))
    repository: Repository = field(default_factory=InMemoryRepository)
    canonical: FakeCanonicalizer = field(default_factory=FakeCanonicalizer)
    images: InMemoryImageStore | None = None
    """Share one between Worlds on one database."""
    receipts: ReceiptParser | None = None
    """None: the fake parser, which reads recorded receipts (`receipt(...)`)."""
    model: AgentModel | None = None
    """None: a ScriptedAgent fed by `say`."""
    settings: OrchestratorSettings = field(default_factory=OrchestratorSettings)
    last: list[OutboundMessage] = field(default_factory=list)
    outcome: HandleOutcome | None = None

    def __post_init__(self) -> None:
        self.agent = ScriptedAgent()
        self.parser = FakeReceiptParser(self.settings.max_receipt_lines)
        self.images = self.images or InMemoryImageStore(self.clock, SequentialIds("img"))
        self.bot = Orchestrator(
            repository=self.repository,
            images=self.images,
            parser=self.receipts or self.parser,
            canonicalizer=self.canonical,
            agent=self.model or self.agent,
            clock=self.clock,
            ids=SequentialIds(),
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
        reply_to_bot: bool = False,
        quoted_text: str | None = None,
        mentions: tuple[Mention, ...] = (),
    ) -> InboundMessage:
        group = chat is not None
        return InboundMessage(
            message_id=message_id or f"m{next(_MESSAGE_IDS)}",
            conversation=ConversationKey("test", chat or f"dm:{who.phone}"),
            conversation_kind=ConversationKind.GROUP if group else ConversationKind.PERSONAL,
            conversation_name=chat,
            sender_ref=who.ref,
            sender_alt_ref=None,
            sender_phone=who.phone,
            sender_name=who.name,
            addressed_to_bot=addressed and group,
            reply_to_bot=reply_to_bot,
            quoted_text=quoted_text,
            mentions=mentions,
            text=text,
            image=image,
            contact=contact,
            event=event,
        )

    def send(self, message: InboundMessage, steps: Sequence[Step] = ()) -> str:
        self.agent.queue(*steps)
        self.outcome = self.bot.handle(message)
        self.last = list(self.outcome.replies)
        assert self.agent.pending == 0, "the script wasn't used up"
        return "\n".join(m.text for m in self.last)

    def say(
        self,
        who: Someone,
        chat: str | None,
        text: str | None = None,
        *steps: Step,
        image: ImageAttachment | None = None,
        contact: ContactAttachment | None = None,
        addressed: bool = True,
    ) -> str:
        """All reply texts, joined; `chat` None is the speaker's personal chat."""
        message = self.message(who, chat, text, image=image, contact=contact, addressed=addressed)
        return self.send(message, steps)

    def tick(self, *, ack: bool = True) -> str:
        """Run the bot's timer once, acknowledging the batch like a gateway; all texts it
        sent, joined."""
        batch = self.bot.tick()
        if ack:
            assert self.bot.ack(batch.id)
        self.last = list(batch.messages)
        return "\n".join(m.text for m in self.last)

    def in_chat(self, chat: str | None, who: Someone | None = None) -> str:
        """Only the texts of the last replies that went to one chat."""
        ref = chat if chat is not None else f"dm:{who.phone if who else ''}"
        return "\n".join(m.text for m in self.last if m.conversation.ref == ref)

    @property
    def turn_input(self) -> str:
        """What the model was sent on its latest call."""
        return self.agent.requests[-1].turn_input

    def key(self, chat: str | None, who: Someone | None = None) -> ConversationKey:
        return ConversationKey("test", chat or f"dm:{who.phone if who else ''}")

    def person(self, who: Someone) -> Person:
        with self.repository.unit_of_work() as uow:
            found = uow.people.by_phone(who.phone)
        assert found is not None
        return found

    def drafts(self, chat: str | None, who: Someone | None = None) -> list[BillDraft]:
        with self.repository.unit_of_work() as uow:
            return list(uow.drafts.for_conversation(self.key(chat, who), list(DraftState)))

    def transcript(self, chat: str | None, who: Someone | None = None) -> list[ChatMessage]:
        with self.repository.unit_of_work() as uow:
            return list(uow.chat.recent(self.key(chat, who), 1000))

    def model_calls(self, counter: str) -> int:
        """Model calls counted today for a person id, or "install"."""
        with self.repository.unit_of_work() as uow:
            usage = uow.llm_usage.get(counter, local_date(self.clock.now(), self.settings.timezone))
            return usage.calls if usage else 0


def flat(world: World, *people: Someone) -> None:
    """Flat 4B with these people in it, everyone having said hi to the bot 1:1 first."""
    for someone in people:
        world.say(someone, None, "hi")
    first, *rest = people
    world.say(first, FLAT, "hi")
    for someone in rest:
        world.say(someone, FLAT, "join", call("join_group"))

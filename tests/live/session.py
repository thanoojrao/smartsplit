"""The live sessions: a bot on the in-memory fakes with the real chat model (after a scripted
setup), the real receipt reader and canonicalizer, and checks every reply gets (SPEC 8.5)."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.adapters.llm.agent import AnthropicAgent
from smartsplit.adapters.llm.canonicalizer import AnthropicCanonicalizer
from smartsplit.adapters.llm.receipts import AnthropicReceiptParser, anthropic_client
from smartsplit.domain.enums import DraftState, PromptKind, PromptStatus
from smartsplit.domain.messages import ImageAttachment
from smartsplit.domain.model import Bill
from smartsplit.ports.agent import AgentModel, AgentRequest, ModelStep
from smartsplit.ports.llm import CountCall
from smartsplit.ports.repository import Repository
from smartsplit.services.handles import HANDLE
from smartsplit.services.reports import group_report, person_report
from tests.integration.world import Someone, World, flat
from tests.live.keys import live_key
from tests.live.report import SCENARIOS, ScenarioLog

CHAT_MODEL = os.environ.get("SMARTSPLIT_LIVE_CHAT_MODEL", "claude-haiku-5-5")
RECEIPT_MODEL = os.environ.get("SMARTSPLIT_RECEIPT_MODEL", "claude-sonnet-5-5")
RECEIPT = Path(__file__).parents[1] / "fixtures" / "receipts" / "live_cafe_receipt.png"
MARKDOWN = re.compile(r"\*\*|__|```|^#{1,6} |^\s*[-*] \S", re.MULTILINE)


class Switch:
    """The scripted agent for setup, then the real model for the conversation under test;
    `words` keeps what the real model itself said this message (its steps without tools)."""

    def __init__(self) -> None:
        self.current: AgentModel | None = None
        self.words: list[str] = []

    def step(self, request: AgentRequest, count_call: CountCall) -> ModelStep:
        assert self.current is not None
        step = self.current.step(request, count_call)
        if not step.tool_calls and step.text:
            self.words.append(step.text)
        return step


@dataclass
class Live:
    world: World
    switch: Switch
    real: AgentModel
    log: ScenarioLog

    def go_live(self) -> None:
        self.switch.current = self.real

    def say(
        self,
        who: Someone,
        chat: str | None,
        text: str | None,
        *,
        image: ImageAttachment | None = None,
        addressed: bool = True,
    ) -> str:
        """One message to the real model; the reply is checked for SPEC 8.5's style."""
        self.switch.words = []
        reply = self.world.say(who, chat, text, image=image, addressed=addressed)
        self.log.messages += 1
        own_words = "\n".join(self.switch.words)
        self.log.asked += "?" in own_words
        self.log.lines.append(f"{who.name} in {chat or 'personal'}: {text} -> {reply!r}")
        assert not HANDLE.search(reply), f"internal handle in the reply: {reply!r}"
        assert not MARKDOWN.search(reply), f"markdown in the reply: {reply!r}"
        assert own_words.count("?") <= 1, f"more than one question: {reply!r}"
        return reply

    def bills(self, who: Someone) -> list[Bill]:
        """Saved bills with this person in them, reversals included, oldest first."""
        person_id = self.world.person(who).id
        with self.world.repository.unit_of_work() as uow:
            return list(uow.bills.for_participant(person_id))

    def owes(self, debtor: Someone, creditor: Someone) -> int:
        """What `debtor` owes `creditor` overall, in cents (negative: the other way)."""
        creditor_id, debtor_id = self.world.person(creditor).id, self.world.person(debtor).id
        with self.world.repository.unit_of_work() as uow:
            rows = person_report(uow, creditor_id) or ()
        return sum(r.cents for r in rows if r.other_id == debtor_id)

    def participants(self, chat: str | None, who: Someone | None = None) -> set[str]:
        """Who is on the one draft under review in this chat."""
        drafts = [d for d in self.world.drafts(chat, who) if d.state is DraftState.REVIEWING]
        assert len(drafts) == 1, drafts
        return set(drafts[0].participants)

    def group_balance(self, group_name: str, who: Someone) -> int:
        """What a group owes `who` (positive) or `who` owes it (negative), in cents."""
        person_id = self.world.person(who).id
        with self.world.repository.unit_of_work() as uow:
            chat = uow.conversations.get(self.world.key(group_name))
            assert chat is not None and chat.group_id is not None
            report = group_report(uow, chat.group_id)
        assert report is not None
        return sum(b.cents for b in report.balances if b.person_id == person_id)

    def open_actions(self, chat: str | None, who: Someone | None = None) -> int:
        with self.world.repository.unit_of_work() as uow:
            prompts = uow.prompts.for_conversation(self.world.key(chat, who), [PromptStatus.OPEN])
        return sum(p.kind is PromptKind.PENDING_ACTION for p in prompts)

    def reviewing(self, chat: str | None, who: Someone | None = None) -> list[int]:
        """Totals of the drafts under review in this chat."""
        return [
            d.total_cents for d in self.world.drafts(chat, who) if d.state is DraftState.REVIEWING
        ]


def live(
    request: pytest.FixtureRequest, *people: Someone, repository: Repository | None = None
) -> Live:
    """Flat 4B with these people (scripted), then the real chat model from here on; on the
    in-memory fakes unless a repository (Postgres) is given."""
    client = anthropic_client(live_key(), timeout_seconds=60)
    switch = Switch()
    world = World(
        repository=repository or InMemoryRepository(),
        model=switch,
        receipts=AnthropicReceiptParser(
            client, model=RECEIPT_MODEL, max_tokens=16000, max_lines=150
        ),
        canonical=AnthropicCanonicalizer(client, model=CHAT_MODEL, max_tokens=16000),
    )
    switch.current = world.agent
    flat(world, *people)
    log = SCENARIOS.setdefault(request.node.name, ScenarioLog())
    real = AnthropicAgent(client, model=CHAT_MODEL, max_tokens=16000)
    session = Live(world, switch, real, log)
    session.go_live()
    return session


GROCERY = Path(__file__).parents[1] / "fixtures" / "receipts" / "live_grocery_receipt.png"
"""19 lines, ₹5,967.00 + 5% GST = ₹6,265.35 (Freshmart, 22-11-2026)."""


def grocery() -> ImageAttachment:
    return ImageAttachment("image/png", GROCERY.read_bytes())


def photo() -> ImageAttachment:
    return ImageAttachment("image/png", RECEIPT.read_bytes())

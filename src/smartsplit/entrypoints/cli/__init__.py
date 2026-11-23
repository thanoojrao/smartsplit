"""Typer CLI channel (SPEC section 11): a chat app in the terminal, for demos and trials.

Each person is known to the CLI by name (their chat identity is the name); `person add`
gives the number. `--in personal` is the person's own chat with the bot, anything else is a
group chat by that name. Every reply is printed under the chat it went to.
"""

import mimetypes
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from smartsplit.adapters.fakes.agent import ScriptedAgent
from smartsplit.adapters.fakes.llm import DEMO_ITEMS, FakeCanonicalizer, FakeReceiptParser
from smartsplit.config import Settings
from smartsplit.domain.enums import ConversationKind, RuleSource
from smartsplit.domain.messages import ImageAttachment, InboundMessage, OutboundMessage
from smartsplit.domain.phone import normalize_phone
from smartsplit.domain.values import ConversationKey
from smartsplit.entrypoints.cli.demo import DEMO, Line, receipt_bytes
from smartsplit.entrypoints.wiring import App, Models, build
from smartsplit.ports.images import ImageStore
from smartsplit.ports.repository import Repository
from smartsplit.ports.system import Clock
from smartsplit.services import Orchestrator
from smartsplit.services.reports import person_report, rules_report
from smartsplit.services.text import money

CHANNEL = "cli"
PERSONAL = "personal"


@dataclass(frozen=True, slots=True)
class Bot:
    orchestrator: Orchestrator
    repository: Repository
    images: ImageStore
    clock: Clock
    currency: str
    region: str
    max_image_bytes: int


type Connect = Callable[[], Bot]
"""Builds the bot on the real models (`say` and `receipt add` need an API key)."""
type ConnectDemo = Callable[[ScriptedAgent], Bot]
"""Builds the bot with the demo's scripted agent and recorded receipts (no key)."""

As = Annotated[str, typer.Option("--as", help="Who is speaking (a name from `person add`).")]
In = Annotated[str, typer.Option("--in", help='"personal" or a group name.')]


def make_cli(connect: Connect, connect_demo: ConnectDemo) -> typer.Typer:
    """The CLI around whatever `connect` builds, so tests can run it on the fakes."""
    cli = typer.Typer(no_args_is_help=True, add_completion=False)
    person, group, member, receipt, images = (
        _subcommand(cli, name) for name in ("person", "group", "member", "receipt", "images")
    )
    state: dict[str, Bot] = {}

    @cli.callback(invoke_without_command=True)
    def main(context: typer.Context) -> None:
        if context.invoked_subcommand != "demo":
            state["bot"] = connect()

    @cli.command()
    def demo() -> None:
        """Play a short scripted conversation through the real bot and database (no key)."""
        agent = ScriptedAgent()
        state["bot"] = connect_demo(agent)
        for line in DEMO:
            agent.queue(*line.steps)
            _echo_line(line)
            image = ImageAttachment("image/jpeg", receipt_bytes()) if line.receipt else None
            send(line.speaker, line.where, line.text, phone=line.phone, image=image)

    def send(
        speaker: str,
        where: str,
        text: str | None,
        *,
        phone: str | None = None,
        image: ImageAttachment | None = None,
    ) -> None:
        bot = state["bot"]
        outcome = bot.orchestrator.handle(_message(speaker, where, text, phone, image))
        replies = [*outcome.replies, *bot.orchestrator.tick()]
        _print(bot, speaker, replies)

    @person.command("add")
    def person_add(name: str, phone: str) -> None:
        """Someone says hi to the bot in their own chat (that's how people join)."""
        try:
            normalize_phone(phone, state["bot"].region)
        except ValueError as error:
            raise typer.BadParameter(f"{phone} isn't a phone number") from error
        send(name, PERSONAL, "hi", phone=phone)

    @group.command("create")
    def group_create(name: str, speaker: As) -> None:
        """The first message in a new group chat creates the group; the speaker joins."""
        send(speaker, name, "hi")

    @member.command("add")
    def member_add(group_name: str, name: str) -> None:
        """They say "join" in the group chat."""
        send(name, group_name, "join")

    @receipt.command("add")
    def receipt_add(
        image: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
        speaker: As,
        where: In,
        caption: Annotated[str | None, typer.Option(help='e.g. "split with Sam".')] = None,
    ) -> None:
        """A receipt photo, read by the real model."""
        if image.stat().st_size > state["bot"].max_image_bytes:
            raise typer.BadParameter("that image is too large")
        mime = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
        send(speaker, where, caption, image=ImageAttachment(mime, image.read_bytes()))

    @cli.command()
    def say(text: str, speaker: As, where: In) -> None:
        """Anything you'd type in the chat."""
        send(speaker, where, text)

    _operator_commands(cli, images, state)
    return cli


def _operator_commands(cli: typer.Typer, images: typer.Typer, state: dict[str, Bot]) -> None:
    """Reads and upkeep for whoever runs the bot."""

    @images.command("prune")
    def images_prune(
        older_than_days: Annotated[int, typer.Option(min=1, help="Keep newer images.")] = 30,
    ) -> None:
        """Delete stored receipt images older than this (SPEC 12.4)."""
        bot = state["bot"]
        cutoff = bot.clock.now() - timedelta(days=older_than_days)
        typer.echo(f"Deleted {bot.images.prune(cutoff)} images.")

    @cli.command()
    def balances(speaker: As) -> None:
        """What someone owes and is owed, per person and place."""
        _show_balances(state["bot"], speaker)

    @cli.command()
    def rules(about: Annotated[str, typer.Option(help="Whose rules.")]) -> None:
        """Every rule about someone, with where it applies and who set it."""
        _show_rules(state["bot"], about)

    @cli.command()
    def tick() -> None:
        """Run the timer once: deliver messages, nudge or expire idle bills."""
        bot = state["bot"]
        _print(bot, None, bot.orchestrator.tick())


def _echo_line(line: Line) -> None:
    if line.note:
        typer.echo(f"\n# {line.note}")
    photo = " [receipt photo]" if line.receipt else ""
    typer.echo(f"{line.speaker} in {line.where}: {line.text or ''}{photo}")


def _ref(name: str) -> str:
    return name.strip().casefold()


def _chat(speaker: str, where: str) -> tuple[ConversationKey, ConversationKind]:
    if where.strip().casefold() == PERSONAL:
        return ConversationKey(CHANNEL, f"dm:{_ref(speaker)}"), ConversationKind.PERSONAL
    return ConversationKey(CHANNEL, f"group:{where.strip()}"), ConversationKind.GROUP


def _message(
    speaker: str, where: str, text: str | None, phone: str | None, image: ImageAttachment | None
) -> InboundMessage:
    """What a chat app would send; in a group everything typed here is addressed to the bot."""
    key, kind = _chat(speaker, where)
    return InboundMessage(
        message_id=uuid.uuid4().hex,
        conversation=key,
        conversation_kind=kind,
        conversation_name=None if kind is ConversationKind.PERSONAL else where.strip(),
        sender_ref=_ref(speaker),
        sender_alt_ref=None,
        sender_phone=phone,
        sender_name=speaker.strip(),
        addressed_to_bot=kind is ConversationKind.GROUP,
        reply_to_bot=False,
        text=text,
        image=image,
    )


def _print(bot: Bot, speaker: str | None, replies: list[OutboundMessage]) -> None:
    """Each reply under its chat: a group by name, the speaker's own chat as "you", anyone
    else's personal chat by their name."""
    me = _known_id(bot, speaker) if speaker else None
    with bot.repository.unit_of_work() as uow:
        for reply in replies:
            ref = reply.conversation.ref
            if ref.startswith("group:"):
                header = ref.removeprefix("group:")
            elif reply.recipient_id is None or reply.recipient_id == me:
                header = "you"
            else:
                person = uow.people.get(reply.recipient_id)
                header = f"to {person.display_name if person else 'someone'}"
            typer.echo(f"[{header}]")
            for line in reply.text.splitlines():
                typer.echo(f"  {line}")


def _signed(cents: int, currency: str) -> str:
    """ "owes you ₹10.00" from the asker's side, or "you owe ₹10.00"."""
    if cents >= 0:
        return f"owes you {money(cents, currency)}"
    return f"you owe {money(-cents, currency)}"


def _subcommand(cli: typer.Typer, name: str) -> typer.Typer:
    sub = typer.Typer(no_args_is_help=True)
    cli.add_typer(sub, name=name)
    return sub


def _known_id(bot: Bot, name: str) -> str | None:
    with bot.repository.unit_of_work() as uow:
        identity = uow.identities.get(CHANNEL, _ref(name))
    return identity.person_id if identity else None


def _person_id(bot: Bot, name: str) -> str:
    person_id = _known_id(bot, name)
    if person_id is None:
        raise typer.BadParameter(f"no person called {name}; use `person add`")
    return person_id


def _show_balances(bot: Bot, name: str) -> None:
    person_id = _person_id(bot, name)
    with bot.repository.unit_of_work() as uow:
        report = person_report(uow, person_id) or ()
    if not report:
        typer.echo("All settled up.")
    for other in report:
        typer.echo(f"{other.name}: {_signed(other.cents, bot.currency)}")
        for part in other.by_context:
            typer.echo(f"  {part.context}: {_signed(part.cents, bot.currency)}")


def _show_rules(bot: Bot, name: str) -> None:
    person_id = _person_id(bot, name)
    with bot.repository.unit_of_work() as uow:
        report = rules_report(uow, person_id) or ()
    if not report:
        typer.echo("No rules.")
    for rule in report:
        how = "learned" if rule.source is RuleSource.LEARNED else f"set by {rule.author}"
        typer.echo(f"{rule.item}: {rule.kind.value} ({rule.scope}, {how})")


def _connect() -> Bot:
    """The real thing: settings from the environment, Postgres, files, and the model."""
    return _bot(build(Settings()))


def _connect_demo(agent: ScriptedAgent) -> Bot:
    """The real bot and database, with the scripted agent and the recorded-receipt parser."""
    settings = Settings()
    models = Models(
        FakeReceiptParser(settings.max_receipt_lines), FakeCanonicalizer(DEMO_ITEMS), agent
    )
    return _bot(build(settings, models))


def _bot(built: App) -> Bot:
    settings = built.settings
    return Bot(
        built.orchestrator,
        built.repository,
        built.images,
        built.clock,
        settings.currency,
        settings.default_region,
        settings.max_image_bytes,
    )


app = make_cli(_connect, _connect_demo)
"""The `smartsplit` console script."""

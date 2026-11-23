"""Typer CLI channel (SPEC section 11): a chat app in the terminal, for demos and trials.

Each person is known to the CLI by name (their chat identity is the name); `person add`
gives the number. `--in personal` is the person's own chat with the bot, anything else is a
group chat by that name. Every reply is printed under the chat it went to.
"""

import mimetypes
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from smartsplit.config import Settings
from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.messages import ImageAttachment, InboundMessage, OutboundMessage
from smartsplit.domain.values import ConversationKey
from smartsplit.entrypoints.wiring import build
from smartsplit.ports.repository import Repository
from smartsplit.services import Orchestrator
from smartsplit.services.reports import person_report, rules_report
from smartsplit.services.text import money

CHANNEL = "cli"
PERSONAL = "personal"


@dataclass(frozen=True, slots=True)
class Bot:
    orchestrator: Orchestrator
    repository: Repository
    currency: str


type Connect = Callable[[bool], Bot]
"""Builds the bot; the flag is `--live` (the real model instead of the offline stand-ins)."""

As = Annotated[str, typer.Option("--as", help="Who is speaking (a name from `person add`).")]
In = Annotated[str, typer.Option("--in", help='"personal" or a group name.')]


def make_cli(connect: Connect) -> typer.Typer:
    """The CLI around whatever `connect` builds, so tests can run it on the fakes."""
    cli = typer.Typer(no_args_is_help=True, add_completion=False)
    person = typer.Typer(no_args_is_help=True, help="People.")
    group = typer.Typer(no_args_is_help=True, help="Groups.")
    member = typer.Typer(no_args_is_help=True, help="Group members.")
    receipt = typer.Typer(no_args_is_help=True, help="Receipts.")
    for sub, name in (
        (person, "person"),
        (group, "group"),
        (member, "member"),
        (receipt, "receipt"),
    ):
        cli.add_typer(sub, name=name)
    state: dict[str, Bot] = {}

    @cli.callback()
    def main(live: Annotated[bool, typer.Option(help="Use the real model.")] = False) -> None:
        state["bot"] = connect(live)

    def send(
        speaker: str,
        where: str,
        text: str | None,
        *,
        phone: str | None = None,
        image: ImageAttachment | None = None,
    ) -> None:
        bot = state["bot"]
        replies = bot.orchestrator.handle(_message(speaker, where, text, phone, image))
        replies += bot.orchestrator.tick()
        _print(bot, speaker, replies)

    @person.command("add")
    def person_add(name: str, phone: str) -> None:
        """Someone says hi to the bot in their own chat (that's how people join)."""
        send(name, PERSONAL, "help", phone=phone)

    @group.command("create")
    def group_create(name: str, speaker: As) -> None:
        """The first message in a new group chat creates the group; the speaker joins."""
        send(speaker, name, "help")

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
        """A receipt photo, or with the offline parser a recorded receipt (.json)."""
        mime = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
        send(speaker, where, caption, image=ImageAttachment(mime, image.read_bytes()))

    @cli.command()
    def say(text: str, speaker: As, where: In) -> None:
        """Anything you'd type in the chat."""
        send(speaker, where, text)

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

    return cli


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
    """Each reply under its chat: a group by name, a personal chat by whose it is."""
    with bot.repository.unit_of_work() as uow:
        for reply in replies:
            if reply.recipient_id is None:
                header = reply.conversation.ref.removeprefix("group:")
            else:
                person = uow.people.get(reply.recipient_id)
                name = person.display_name if person else "someone"
                mine = speaker is not None and name.casefold() == _ref(speaker)
                header = "you" if mine else f"to {name}"
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


def _person_id(bot: Bot, name: str) -> str:
    with bot.repository.unit_of_work() as uow:
        identity = uow.identities.get(CHANNEL, _ref(name))
    if identity is None:
        raise typer.BadParameter(f"no person called {name}; use `person add`")
    return identity.person_id


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
        typer.echo(f"{rule.item}: {rule.kind.value} ({rule.scope}, {rule.source.value})")


def _connect(live: bool) -> Bot:
    """The real thing: settings from the environment, Postgres, files, and the model if live."""
    built = build(Settings(), live=live)
    return Bot(built.orchestrator, built.repository, built.settings.currency)


app = make_cli(_connect)
"""The `smartsplit` console script."""

"""Plain chat text: money, names, help (SPEC section 10.1: short lines, no tables)."""

from datetime import date

from smartsplit.domain.money import format_cents
from smartsplit.domain.phone import mask_phone
from smartsplit.ports.repository import UnitOfWork

_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}

HELP = """I split bills. Send a receipt photo, or write a bill like "rent 30000 with Sam and Raj".
In a group, everyone in it shares by default: "split with me and Priya" or "everyone except Raj".
Tell me what people don't use: "Raj doesn't drink milk", "Sam usually skips chips".
Ask "balances" or "what do I owe Sam?". Say "details" during a review to see every line."""


TRY_AGAIN = "Couldn't do that, try again in a minute."
READ_LATER = "Couldn't read the receipt just now. I'll try again shortly."
OVER_LIMIT = "That's all I can do for you today. Try again tomorrow."
NEEDS_NUMBER = "Message me 1:1 first, so I can link this chat to your number."


def money(cents: int, currency: str) -> str:
    """₹1,234.50 for INR; "CHF 12.00" for codes without a familiar symbol."""
    symbol = _SYMBOLS.get(currency)
    text = format_cents(abs(cents))
    sign = "-" if cents < 0 else ""
    return f"{sign}{symbol}{text}" if symbol else f"{sign}{currency} {text}"


def name_for(uow: UnitOfWork, viewer_id: str | None, person_id: str) -> str:
    """What the viewer calls this person: their own nickname, else the person's display name.

    In a group chat (viewer None) everyone sees the display name. A number is never shown in
    full (SPEC section 6.1).
    """
    if viewer_id is not None:
        for nickname in uow.nicknames.for_owner(viewer_id):
            if nickname.subject_id == person_id:
                return nickname.name.title() if nickname.name.islower() else nickname.name
    person = uow.people.get(person_id)
    if person is None:
        return "someone"
    return person.display_name or mask_phone(person.phone)


def join_names(names: list[str]) -> str:
    """ "Sam", "Sam and Raj", "Sam, Raj and Priya"."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def day_label(day: date) -> str:
    """ "21 Nov": short, and the same on every platform."""
    return f"{day.day} {day:%b}"

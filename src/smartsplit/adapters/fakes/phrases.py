"""Phrase-level helpers for the keyword interpreter: amounts, names, lines, builders."""

import re
from decimal import Decimal, InvalidOperation

from smartsplit.domain.commands import (
    AddManualBill,
    Command,
    Edit,
    StartSplit,
)
from smartsplit.domain.edits import (
    AssignLine,
    SetPayer,
)
from smartsplit.domain.values import ExactAmount, LineRef
from smartsplit.ports.llm import InterpretContext

AMOUNT = r"(?:₹|rs\.?\s*|\$)?(\d[\d,]*(?:\.\d{1,2})?)"
NAMED_AMOUNT = r"(?:₹|rs\.?\s*|\$)?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)"
NAME = r"([A-Za-z][\w'-]*)"
PHONE = r"(\+?[\d][\d\s-]{6,}\d)"
SELF = {"i", "me", "myself"}


def cents(text: str) -> int:
    """ "1,200.50" → 120050. Commas are thousands separators."""
    try:
        value = Decimal(text.replace(",", ""))
    except InvalidOperation as error:
        raise ValueError(f"not an amount: {text!r}") from error
    return int(value * 100)


def person(name: str) -> str | None:
    """None for the speaker, otherwise the name as written."""
    return None if name.lower() in SELF else name


def names(text: str) -> tuple[str, ...]:
    """ "Sam, Raj and Priya" → ("Sam", "Raj", "Priya"); "me" stays as said."""
    parts = re.split(r",\s*|\s+and\s+|\s*&\s*", text.strip())
    return tuple(part.strip() for part in parts if part.strip())


def line_ref(text: str) -> LineRef:
    """ "line 4" or "4" → 4; anything else is a name ("the wine" → "wine")."""
    cleaned = re.sub(r"^(?:line\s+|the\s+)", "", text.strip(), flags=re.IGNORECASE)
    return int(cleaned) if cleaned.isdigit() else cleaned


def split(match: re.Match[str], context: InterpretContext) -> Command:
    if context.draft_lines and match["payer"] and not match["with"]:
        return Edit(SetPayer(match["payer"]))
    who = match["with"] or ""
    everyone = bool(re.match(r"everyone\b", who, re.IGNORECASE))
    excluding = re.search(r"except\s+(.+)$", who, re.IGNORECASE)
    return StartSplit(
        people=() if everyone or not who else names(who),
        everyone=everyone,
        excluding=names(excluding[1]) if excluding else (),
        payer=match["payer"] or None,
        owes_all=match["owes_all"] or None,
    )


def manual(match: re.Match[str], _: InterpretContext) -> Command:
    exact = tuple(
        ExactAmount(name, cents(amount))
        for name, amount in re.findall(rf"{NAME}\s+{AMOUNT}", match["exact"] or "")
    )
    who = match["with"] or ""
    return AddManualBill(
        description=match["desc"].strip(),
        amount=cents(match["amount"]),
        people=tuple(e.person for e in exact) or (names(who) if who else ()),
        exact=exact,
    )


def only_line(context: InterpretContext) -> LineRef:
    """Without a line name, an edit applies to the only line, if the bill has just one."""
    if len(context.draft_lines) != 1:
        raise ValueError("which line?")
    return 1


def weights(match: re.Match[str], context: InterpretContext) -> Command:
    """ "2 for Sam, 1 for Raj on the yogurt" or "2 yogurts for Sam, 1 for Raj"."""
    pairs = re.findall(rf"(\d+)\s+(?:(\w+)\s+)?for\s+{NAME}", match["pairs"])
    item = match["line"] or next((word for _, word, _ in pairs if word), None)
    line = line_ref(item) if item else only_line(context)
    return Edit(AssignLine(line, weights=tuple((name, int(w)) for w, _, name in pairs)))


def percent(match: re.Match[str], context: InterpretContext) -> Command:
    """ "70/30 for Sam and Raj (on the cab)": weights in the order the people are named."""
    people = names(match["people"])
    shares = (int(match["first"]), int(match["second"]))
    if len(people) != len(shares):
        raise ValueError("one share per person")
    line = line_ref(match["line"]) if match["line"] else only_line(context)
    return Edit(AssignLine(line, weights=tuple(zip(people, shares, strict=True))))


def part(match: re.Match[str], context: InterpretContext) -> Command:
    """ "Sam's part was 100" (the only line) or "Sam's part of the wine was 100"."""
    line = line_ref(match["line"]) if match["line"] else only_line(context)
    return Edit(AssignLine(line, exact=(ExactAmount(match["who"], cents(match["amount"])),)))

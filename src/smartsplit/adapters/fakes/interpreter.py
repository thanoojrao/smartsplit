"""Keyword/regex CommandInterpreter: good enough for tests and the CLI demo (SPEC section 8).

Patterns are tried in order; the first match wins. Names are kept as written ("Sam"); "I",
"me" and "myself" mean the speaker. Amounts like "500", "₹1,200.50" become integer cents.
"""

import re
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation

from smartsplit.adapters.fakes.llm import FakeCanonicalizer
from smartsplit.domain.commands import (
    Acknowledge,
    AddManualBill,
    AddPerson,
    AddRule,
    AnswerPrompt,
    CancelDraft,
    Command,
    ConfirmDraft,
    CorrectNumber,
    DeleteBill,
    DeleteRule,
    Edit,
    FileIntoGroup,
    Help,
    JoinGroup,
    ListRules,
    MemberLeft,
    Notifications,
    NotMine,
    NotReceived,
    RecordPayment,
    Remind,
    SetNickname,
    ShowBalances,
    ShowBillDetails,
    ShowHistory,
    SquareUp,
    StartSplit,
    UndoPayment,
    Unknown,
)
from smartsplit.domain.edits import (
    AcceptDifference,
    AddLine,
    AssignLine,
    NotThisItem,
    RemoveLine,
    SetLineAmount,
    SetPayer,
    SetTotal,
    UnassignLine,
)
from smartsplit.domain.enums import RuleKind
from smartsplit.domain.values import ExactAmount, LastBill, LineRef, NumberedBill
from smartsplit.ports.llm import InterpretContext

AMOUNT = r"(?:₹|rs\.?\s*|\$)?(\d[\d,]*(?:\.\d{1,2})?)"
NAMED_AMOUNT = r"(?:₹|rs\.?\s*|\$)?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)"
NAME = r"([A-Za-z][\w'-]*)"
PHONE = r"(\+?[\d][\d\s-]{6,}\d)"
SELF = {"i", "me", "myself"}

type Rule = tuple[re.Pattern[str], Callable[[re.Match[str], InterpretContext], Command]]


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


def _rule(pattern: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{pattern}\s*[.!?]*\s*$", re.IGNORECASE)


def _split(match: re.Match[str], context: InterpretContext) -> Command:
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


def _manual(match: re.Match[str], _: InterpretContext) -> Command:
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


def _weights(match: re.Match[str], _: InterpretContext) -> Command:
    pairs = re.findall(rf"(\d+)\s+for\s+{NAME}", match["pairs"])
    return Edit(AssignLine(line_ref(match["line"]), weights=tuple((n, int(w)) for w, n in pairs)))


RULES: Sequence[Rule] = [
    (_rule(r"(?:yes|y|yeah|yep|sure)"), lambda m, c: AnswerPrompt(yes=True)),
    (_rule(r"(?:no|nope|n)"), lambda m, c: AnswerPrompt(yes=False)),
    (_rule(r"(\d+)"), lambda m, c: AnswerPrompt(choice=int(m[1]))),
    (_rule(r"(?:ok|okay|thanks|thank you|cool)"), lambda m, c: Acknowledge()),
    (_rule(r"help"), lambda m, c: Help()),
    (_rule(r"stop"), lambda m, c: Notifications(on=False)),
    (_rule(r"start"), lambda m, c: Notifications(on=True)),
    (_rule(r"cancel"), lambda m, c: CancelDraft()),
    (_rule(r"(?:confirm|save(?: it)?|looks good|done)"), lambda m, c: ConfirmDraft()),
    (_rule(r"join"), lambda m, c: JoinGroup()),
    (_rule(r"not received"), lambda m, c: NotReceived()),
    (_rule(r"undo(?: (?:the|my))?(?: last)? payment"), lambda m, c: UndoPayment()),
    (_rule(rf"square up with {NAME}"), lambda m, c: SquareUp(m[1])),
    (_rule(rf"remind {NAME}"), lambda m, c: Remind(m[1])),
    (_rule(r"not mine"), lambda m, c: NotMine()),
    (
        _rule(r"details(?: (\d+))?"),
        lambda m, c: ShowBillDetails(NumberedBill(int(m[1])) if m[1] else None),
    ),
    (
        _rule(r"delete (?:the |my )?last bill(?:,? because (.+))?"),
        lambda m, c: DeleteBill(LastBill(), m[1]),
    ),
    (_rule(r"add (?:it |this )?to (.+)"), lambda m, c: FileIntoGroup(m[1].strip())),
    (
        _rule(r"what did i spend (this|last) month"),
        lambda m, c: ShowHistory(period="this_month" if m[1].lower() == "this" else "last_month"),
    ),
    (_rule(r"(?:show )?(?:my )?last (\d+) bills"), lambda m, c: ShowHistory(last_n=int(m[1]))),
    (
        _rule(rf"(?:what do i owe|balance with|what does) {NAME}(?: owe(?: me)?)?"),
        lambda m, c: ShowBalances(with_person=m[1]),
    ),
    (_rule(r"balances?(?: in (.+))?"), lambda m, c: ShowBalances(group_name=m[1])),
    (
        _rule(rf"(?:i )?paid {NAME} {AMOUNT}(?: for (.+))?"),
        lambda m, c: RecordPayment(cents(m[2]), payee=m[1], context_name=m[3]),
    ),
    (
        _rule(rf"{NAME} paid me {AMOUNT}(?: for (.+))?"),
        lambda m, c: RecordPayment(cents(m[2]), payer=m[1], context_name=m[3]),
    ),
    (_rule(rf"rules about {NAME}"), lambda m, c: ListRules(person(m[1]))),
    (
        _rule(rf"{NAME} (?:usually|mostly) (?:doesn'?t|don'?t) (?:eat|drink|use|have) (.+)"),
        lambda m, c: AddRule(m[2], RuleKind.SOFT_EXCLUDE, person(m[1])),
    ),
    (
        _rule(rf"(?:don'?t|never) add (.+) to {NAME}"),
        lambda m, c: AddRule(m[1], RuleKind.EXCLUDE, person(m[2])),
    ),
    (
        _rule(rf"{NAME} (?:doesn'?t|don'?t|never) (?:eat|drink|use|share)s? (.+)"),
        lambda m, c: AddRule(m[2], RuleKind.EXCLUDE, person(m[1])),
    ),
    (
        _rule(rf"(.+?) is (?:only )?{NAME}'s"),
        lambda m, c: AddRule(m[1], RuleKind.ONLY, person(m[2])),
    ),
    (
        _rule(rf"{NAME} (?:drinks|eats|uses|has) (.+) now"),
        lambda m, c: DeleteRule(m[2], person(m[1])),
    ),
    (_rule(rf"{NAME} moved out"), lambda m, c: MemberLeft(person(m[1]))),
    (_rule(rf"call {NAME} {NAME}"), lambda m, c: SetNickname(m[1], m[2])),
    (_rule(rf"{NAME}'s number is {PHONE}"), lambda m, c: CorrectNumber(m[1], m[2])),
    (_rule(rf"add {NAME} {PHONE}"), lambda m, c: AddPerson(m[1], m[2])),
    (
        _rule(rf"line (\d+) is {AMOUNT}"),
        lambda m, c: Edit(SetLineAmount(int(m[1]), cents(m[2]))),
    ),
    (_rule(r"remove (.+)"), lambda m, c: Edit(RemoveLine(line_ref(m[1])))),
    (_rule(rf"total is {AMOUNT}"), lambda m, c: Edit(SetTotal(cents(m[1])))),
    (_rule(r"accept(?: the)? difference"), lambda m, c: Edit(AcceptDifference())),
    (
        _rule(r"that'?s not (?:the )?(.+?)(?:,? it'?s (?:a |an |the )?(.+))?"),
        lambda m, c: Edit(NotThisItem(m[1], m[2])),
    ),
    (
        _rule(rf"{NAME} had none of (.+)"),
        lambda m, c: Edit(UnassignLine(line_ref(m[2]), (m[1],))),
    ),
    (
        _rule(rf"{NAME}'s part of (.+) was {AMOUNT}"),
        lambda m, c: Edit(AssignLine(line_ref(m[2]), exact=(ExactAmount(m[1], cents(m[3])),))),
    ),
    (_rule(r"(?P<pairs>(?:\d+ for \w+(?:,\s*|\s+and\s+)?)+) (?:on|of) (?P<line>.+)"), _weights),
    (_rule(rf"add (.+?) {AMOUNT}"), lambda m, c: Edit(AddLine(m[1], cents(m[2])))),
    (_rule(rf"add {NAME}"), lambda m, c: AddPerson(m[1])),
    (
        _rule(
            r"split(?: this)?(?: with (?P<with>.+?))?(?:,?\s*(?P<payer>\w+) paid)?"
            r"(?:,?\s*(?P<owes_all>\w+) owes all(?: of it)?)?"
        ),
        _split,
    ),
    (_rule(r"(?P<payer>\w+) paid(?P<with>)(?P<owes_all>)"), _split),
    (
        _rule(
            rf"(?P<desc>[a-z][a-z ]*?) {NAMED_AMOUNT}"
            r"(?::\s*(?P<exact>.+)|\s+(?:with\s+)?(?P<with>.+))?"
        ),
        _manual,
    ),
]


class KeywordInterpreter:
    """Regex stand-in for the model; canonicalize uses a fixed table like FakeCanonicalizer."""

    def __init__(self, canonical: FakeCanonicalizer | None = None) -> None:
        self._canonical = canonical or FakeCanonicalizer()

    def interpret(self, text: str, context: InterpretContext) -> Command:
        for pattern, build in RULES:
            match = pattern.match(text)
            if match:
                try:
                    return build(match, context)
                except ValueError:
                    return Unknown(text)
        return Unknown(text)

    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str:
        return self._canonical.canonicalize(name, known_keys)

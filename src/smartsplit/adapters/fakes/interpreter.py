"""Keyword/regex CommandInterpreter: good enough for tests and the CLI demo (SPEC section 8).

Patterns are tried in order; the first match wins. Amounts like "500", "₹1,200.50" become
integer cents. Speaker convention: where CONTRACTS says None means the speaker (a rule's
subject, MemberLeft, ListRules), "I"/"me" become None; everywhere else names are kept as said,
"me" included, and the services resolve "me" to the speaker.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import replace

from smartsplit.adapters.fakes.llm import FakeCanonicalizer
from smartsplit.adapters.fakes.phrases import (
    AMOUNT,
    NAME,
    NAMED_AMOUNT,
    PHONE,
    cents,
    line_ref,
    manual,
    names,
    part,
    percent,
    person,
    split,
    weights,
)
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
    AddParticipants,
    NotThisItem,
    RemoveLine,
    RemoveParticipants,
    SetLineAmount,
    SetTotal,
    UnassignLine,
)
from smartsplit.domain.enums import RuleKind
from smartsplit.domain.values import BillRef, LastBill, NamedBill, NumberedBill
from smartsplit.ports.llm import InterpretContext

type Rule = tuple[re.Pattern[str], Callable[[re.Match[str], InterpretContext], Command]]


def _rule(pattern: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{pattern}\s*[.!?]*\s*$", re.IGNORECASE)


RULES: Sequence[Rule] = [
    (_rule(r"(?:yes|y|yeah|yep|sure)"), lambda m, c: AnswerPrompt(yes=True)),
    (_rule(r"(?:no|nope|n)"), lambda m, c: AnswerPrompt(yes=False)),
    (_rule(r"(\d+)"), lambda m, c: AnswerPrompt(choice=int(m[1]))),
    (
        _rule(r"(\d+)[:)]?\s+(yes|no)"),
        lambda m, c: AnswerPrompt(choice=int(m[1]), yes=m[2].lower() == "yes"),
    ),
    (
        _rule(r"(\d+)[:)]\s+(?:just |only )?(.+)"),
        lambda m, c: AnswerPrompt(choice=int(m[1]), people=names(m[2])),
    ),
    (_rule(r"(?:ok|okay|thanks|thank you|cool)"), lambda m, c: Acknowledge()),
    (_rule(r"help"), lambda m, c: Help()),
    (_rule(r"stop"), lambda m, c: Notifications(on=False)),
    (_rule(r"start"), lambda m, c: Notifications(on=True)),
    (_rule(r"cancel"), lambda m, c: CancelDraft()),
    (_rule(r"(?:confirm|save(?: it)?|looks good|done)"), lambda m, c: ConfirmDraft()),
    (_rule(r"join"), lambda m, c: JoinGroup()),
    (
        _rule(r"add (.+?) to (?:the |this )bill"),
        lambda m, c: Edit(AddParticipants(names(m[1]))),
    ),
    (
        _rule(r"(?:remove|take) (.+?) (?:from|off) (?:the |this )bill"),
        lambda m, c: Edit(RemoveParticipants(names(m[1]))),
    ),
    (_rule(r"not received"), lambda m, c: NotReceived()),
    (_rule(r"undo(?: (?:the|my))?(?: last)? payment"), lambda m, c: UndoPayment()),
    (_rule(rf"square up with {NAME}"), lambda m, c: SquareUp(m[1])),
    (_rule(rf"remind {NAME}"), lambda m, c: Remind(m[1])),
    (_rule(r"not mine"), lambda m, c: NotMine()),
    (_rule(r"not mine (\d+)"), lambda m, c: NotMine(NumberedBill(int(m[1])))),
    (_rule(r"delete bill (\d+)"), lambda m, c: DeleteBill(NumberedBill(int(m[1])))),
    (
        _rule(r"(?:edit|change|fix) (?:the )?(.+?) bill:\s*(.+?)(?:,\s*(?:because\s+)?(.+))?"),
        lambda m, c: _aimed(m[2], NamedBill(m[1].strip()), m[3], c),
    ),
    (
        _rule(r"(?:in |on )?(?:the |my )?last bill[,:]\s*(.+)"),
        lambda m, c: _aimed(m[1], LastBill(), None, c),
    ),
    (
        _rule(r"bill (\d+)[,:]\s*(.+)"),
        lambda m, c: _aimed(m[2], NumberedBill(int(m[1])), None, c),
    ),
    (_rule(rf"{NAME} wasn'?t there"), lambda m, c: Edit(RemoveParticipants((m[1],)))),
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
    (_rule(r"(?:what do i owe|who owes what)"), lambda m, c: ShowBalances()),
    (
        _rule(rf"(?:what do i owe|balance with|what does) {NAME}(?: owe(?: me)?)?"),
        lambda m, c: ShowBalances(with_person=m[1]),
    ),
    (_rule(rf"what rules are about {NAME}"), lambda m, c: ListRules(person(m[1]))),
    (
        _rule(rf"{NAME} owes (?:me )?all(?: of it)?"),
        lambda m, c: StartSplit(owes_all=m[1]),
    ),
    (
        _rule(rf"(?P<desc>[a-z][a-z ]*?) {NAMED_AMOUNT},? split (?:all|everyone|between everyone)"),
        lambda m, c: AddManualBill(m["desc"].strip(), cents(m["amount"]), everyone=True),
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
    (_rule(rf"(?P<who>[A-Za-z]\w*)'s part(?: of (?P<line>.+?))? was {NAMED_AMOUNT}"), part),
    (
        _rule(
            r"(?P<pairs>(?:\d+ (?:\w+ )?for \w+(?:,\s*|\s+and\s+)?)+)"
            r"(?: (?:on|of) (?P<line>.+))?"
        ),
        weights,
    ),
    (
        _rule(r"(?P<first>\d+)/(?P<second>\d+) for (?P<people>.+?)(?: on (?P<line>.+))?"),
        percent,
    ),
    (_rule(rf"add (.+?) {AMOUNT}"), lambda m, c: Edit(AddLine(m[1], cents(m[2])))),
    (_rule(rf"add {NAME}"), lambda m, c: AddPerson(m[1])),
    (
        _rule(
            r"split(?: this)?(?: with (?P<with>.+?))?(?:,?\s*(?P<payer>\w+) paid)?"
            r"(?:,?\s*(?P<owes_all>\w+) owes all(?: of it)?)?"
        ),
        split,
    ),
    (_rule(r"(?P<payer>\w+) paid(?P<with>)(?P<owes_all>)"), split),
    (
        _rule(r"(?:with )?everyone except (.+)"),
        lambda m, c: AnswerPrompt(excluding=names(m[1])),
    ),
    (_rule(r"with (.+)"), lambda m, c: AnswerPrompt(people=names(m[1]))),
    (
        _rule(r"((?:\w+,\s*)*\w+\s+and\s+\w+)"),
        lambda m, c: AnswerPrompt(people=names(m[1])),
    ),
    (
        _rule(
            rf"(?P<desc>[a-z][a-z ]*?) {NAMED_AMOUNT}"
            r"(?::\s*(?P<exact>.+)|\s+(?:with\s+)?(?P<with>.+))?"
        ),
        manual,
    ),
]


def _aimed(text: str, target: BillRef, reason: str | None, context: InterpretContext) -> Command:
    """An edit said about a saved bill: the edit as usual, aimed at that bill."""
    command = interpret_text(text, context)
    if isinstance(command, Edit):
        return replace(command, target=target, reason=reason)
    return Unknown(text)


def interpret_text(text: str, context: InterpretContext) -> Command:
    plain = text.replace("\u2019", "'").replace("\u2018", "'")  # phone keyboards' quotes
    for pattern, build in RULES:
        match = pattern.match(plain)
        if match:
            try:
                return build(match, context)
            except ValueError:
                return Unknown(text)
    return Unknown(text)


class KeywordInterpreter:
    """Regex stand-in for the model; canonicalize uses a fixed table like FakeCanonicalizer."""

    def __init__(self, canonical: FakeCanonicalizer | None = None) -> None:
        self._canonical = canonical or FakeCanonicalizer()

    def interpret(self, text: str, context: InterpretContext) -> Command:
        return interpret_text(text, context)

    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str:
        return self._canonical.canonicalize(name, known_keys)

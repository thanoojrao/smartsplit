"""Read tools: balances, a bill line by line, bill lists, rules, finding a person (SPEC 8.3).

They change nothing; whatever they show is rendered by code (SPEC 8.5). In a group chat the
answer covers only that group, and anything wider goes privately (SPEC 10.7).
"""

from typing import Any

from smartsplit.domain.prompts import ChatRef
from smartsplit.domain.tools import FindPerson, GetBalances, GetBill, ListBills, ListRules
from smartsplit.domain.values import GroupContext
from smartsplit.services.bill_changes import bill_details
from smartsplit.services.choosing import known_from
from smartsplit.services.drafting import renderer_for, split_of
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.names import candidates
from smartsplit.services.personal import list_bills
from smartsplit.services.queries import get_balances
from smartsplit.services.rules_chat import list_rules
from smartsplit.services.text import name_for
from smartsplit.services.tools import refs
from smartsplit.services.tools.registry import Data, Tool
from smartsplit.services.turn import Turn


def _get_balances(turn: Turn, args: GetBalances) -> Data:
    other = refs.maybe_person(turn, args.with_person)
    group_id = refs.group(turn, args.group) if args.group else None
    private = get_balances(turn, other, group_id, args.overall)
    return {"sent_privately": private}


def _get_bill(turn: Turn, args: GetBill) -> Data:
    kind = turn.handles.kind_of(args.bill)
    if kind == "draft":
        found = refs.draft(turn, args.bill)
        split = split_of(turn, found)
        turn.show(
            renderer_for(turn).details(found, split),
            (ChatRef("draft", found.id, found.version, split.fingerprint),),
        )
        return {"lines": len(found.lines)}
    bill = refs.bill(turn, args.bill)
    group_id = turn.conversation.group_id
    if group_id is not None and bill.context != GroupContext(group_id):
        raise NotAllowedError("That bill isn't from this group.")
    turn.show(bill_details(turn, bill), (ChatRef("bill", bill.id),))
    return {"lines": len(bill.lines)}


def _list_bills(turn: Turn, args: ListBills) -> Data:
    shown_before = len(turn.shown)
    list_bills(turn, args, refs.maybe_person(turn, args.person))
    listed = [r.id for said in turn.shown[shown_before:] for r in said.refs if r.kind == "bill"]
    handles = []
    for bill_id in listed:
        found = turn.uow.bills.get(bill_id)
        if found is not None:
            handles.append(refs.bill_handle(turn, found))
    return {"bills": handles}


def _list_rules(turn: Turn, args: ListRules) -> Data:
    list_rules(turn, refs.person(turn, args.about))
    return {}


def _find_person(turn: Turn, args: FindPerson) -> Data:
    """Everyone the name can mean to the speaker, with where they know them from."""
    group_id = turn.conversation.group_id
    within = {m.person_id for m in turn.uow.memberships.for_group(group_id)} if group_id else None
    found = candidates(turn.uow, turn.speaker.id, args.name, turn.settings.default_region, within)
    people = []
    for person_id in found:
        person = turn.uow.people.get(person_id)
        if person is None:
            continue
        people.append(
            {
                "person": refs.person_handle(turn, person_id),
                "name": name_for(turn.uow, turn.viewer, person_id),
                "known_from": (
                    [turn.conversation.name or "this group"]
                    if group_id
                    else known_from(turn, turn.speaker.id, person_id)
                ),
            }
        )
    return {"matches": people}


READ_TOOLS: tuple[Tool[Any], ...] = (
    Tool(
        "get_balances",
        "Show balances: here (default), with one person, for one group, or overall. In a "
        "group chat the overall answer is sent privately; this group plus overall shows both.",
        GetBalances,
        _get_balances,
        "past_members",
    ),
    Tool(
        "get_bill",
        "Show a draft (D) or saved bill (B) line by line.",
        GetBill,
        _get_bill,
    ),
    Tool(
        "list_bills",
        "List bills: the last N, a month (sums the speaker's shares), text in the description "
        "such as a shop, or bills with a person.",
        ListBills,
        _list_bills,
    ),
    Tool("list_rules", 'List the rules about a person (P, or "me").', ListRules, _list_rules),
    Tool(
        "find_person",
        "Who a name can mean to the speaker: zero, one or several people, with a handle each.",
        FindPerson,
        _find_person,
        "anyone",
    ),
)

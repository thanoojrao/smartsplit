"""Rules said in chat: adding, deleting and listing, with privacy (SPEC 6.2, 10.7, 12.3).

Your own rules apply at once. A rule about someone else, or deleting one, is restated as a
pending action and needs a later "yes" from the speaker (SPEC 8.4).
"""

from smartsplit.domain.enums import ConversationKind, RuleKind, RuleSource
from smartsplit.domain.model import Rule
from smartsplit.domain.prompts import RuleChangeEffect
from smartsplit.domain.tools import AddRule, DeleteRule
from smartsplit.domain.values import Everywhere, GroupScope, NotesScope, RuleScope
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.pending_types import Proposal
from smartsplit.services.rules import find_stated_rule, propose_stated_rule, put_rule
from smartsplit.services.text import name_for
from smartsplit.services.turn import Turn

RULE_VERSION = 0
"""Rule changes have no version to go stale: a "yes" re-applies the exact rule shown."""


def rule_to_add(turn: Turn, args: AddRule) -> Rule:
    """The rule as it would be stored (`args.subject` is an id), after the permission check."""
    return propose_stated_rule(
        turn.uow,
        rule_id=turn.ids.new_id(),
        conversation_kind=turn.conversation.kind,
        group_id=turn.conversation.group_id,
        subject_id=args.subject,
        item=args.item,
        kind=args.kind,
        author_id=turn.speaker.id,
        now=turn.now,
    )


def rule_to_delete(turn: Turn, args: DeleteRule) -> Rule:
    rule = find_stated_rule(
        turn.uow,
        conversation_kind=turn.conversation.kind,
        group_id=turn.conversation.group_id,
        subject_id=args.subject,
        item=args.item,
        by=turn.speaker.id,
        now=turn.now,
    )
    if rule is None:
        raise NotAllowedError("There's no rule like that here.")
    return rule


def propose_rule_change(turn: Turn, args: AddRule | DeleteRule) -> Proposal:
    """A rule about someone else (or deleting one) is restated first (SPEC 6.2, 8.4)."""
    if isinstance(args, AddRule):
        rule = rule_to_add(turn, args)
        return Proposal(
            RuleChangeEffect(rule, None), RULE_VERSION, f"Save this rule: {describe(turn, rule)}?"
        )
    rule = rule_to_delete(turn, args)
    text = f"Remove this rule: {describe(turn, rule)}?"
    return Proposal(RuleChangeEffect(None, rule.id), RULE_VERSION, text)


def apply_rule_change(turn: Turn, effect: RuleChangeEffect) -> None:
    """The confirmed change, exactly as restated; group changes are announced in the chat."""
    if effect.add is not None:
        put_rule(turn.uow, effect.add)
        turn.show(f"{turn.speaker.display_name} saved a rule: {describe(turn, effect.add)}.")
        return
    rule = turn.uow.rules.get(effect.delete_rule_id or "")
    if rule is None:
        raise NotAllowedError("That rule is already gone.")
    turn.uow.rules.delete(rule.id)
    turn.show(f"{turn.speaker.display_name} removed a rule: {describe(turn, rule)}.")


def list_rules(turn: Turn, subject: str) -> None:
    """In a group: only its rules here, and the full list in the asker's own chat (F13, F14)."""
    rules = turn.uow.rules.for_subjects([subject])
    group_id = turn.conversation.group_id
    if group_id is not None:
        here = [r for r in rules if r.scope == GroupScope(group_id)]
        turn.show(_listing(turn, here, with_scope=False) or "No rules about that here.")
        visible = [r for r in rules if _visible(turn, r)]
        if len(visible) > len(here) and turn.direct(
            turn.speaker.id, _listing(turn, visible, with_scope=True)
        ):
            turn.show("I sent you the full list in a DM.")
        return
    visible = [r for r in rules if _visible(turn, r)]
    turn.show(_listing(turn, visible, with_scope=True) or "No rules about that yet.")


def describe(turn: Turn, rule: Rule) -> str:
    who = name_for(turn.uow, _viewer(turn), rule.subject_id)
    match rule.kind:
        case RuleKind.EXCLUDE:
            return f"{who} never shares {rule.item_key}"
        case RuleKind.SOFT_EXCLUDE:
            return f"{who} usually skips {rule.item_key} (I'll ask)"
        case RuleKind.ONLY:
            return f"{rule.item_key} is {who}'s"


def _listing(turn: Turn, rules: list[Rule], *, with_scope: bool) -> str:
    lines = []
    for rule in rules:
        setter = name_for(turn.uow, _viewer(turn), rule.author_id)
        how = "learned" if rule.source is RuleSource.LEARNED else f"set by {setter}"
        where = f"{_scope_name(turn, rule)}, " if with_scope else ""
        lines.append(f"{describe(turn, rule)} ({where}{how})")
    return "\n".join(lines)


def _scope_name(turn: Turn, rule: Rule) -> str:
    if rule.scope == NotesScope(turn.speaker.id):
        return "your notes"
    return scope_label(turn.uow, rule.scope, _viewer(turn))


def scope_label(uow: UnitOfWork, scope: RuleScope, viewer: str | None = None) -> str:
    """Where a rule applies; notes are named by their owner, as `viewer` calls them."""
    match scope:
        case Everywhere():
            return "everywhere"
        case GroupScope(group_id):
            group = uow.groups.get(group_id)
            return group.name if group else "a group"
        case NotesScope(owner_id):
            return f"{name_for(uow, viewer, owner_id)}'s notes"


def _visible(turn: Turn, rule: Rule) -> bool:
    """Every rule about you (SPEC 6.2: scope and author included), your notes, and the rules
    of groups you are in."""
    me = turn.speaker.id
    if rule.subject_id == me:
        return True
    match rule.scope:
        case Everywhere():
            return False
        case NotesScope(owner_id):
            return owner_id == me
        case GroupScope(group_id):
            return any(m.group_id == group_id for m in turn.uow.memberships.for_person(me))


def _viewer(turn: Turn) -> str | None:
    return None if turn.conversation.kind is ConversationKind.GROUP else turn.speaker.id

"""Stating and deleting rules, with who may do it where (SPEC section 6.2)."""

from datetime import datetime

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import RuleKind, RuleSource
from smartsplit.domain.model import Rule
from smartsplit.domain.values import Everywhere, GroupScope, NotesScope, RuleScope
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.errors import NotAllowedError


def add_stated_rule(
    uow: UnitOfWork,
    *,
    rule_id: str,
    scope: RuleScope,
    subject_id: str,
    item: str,
    kind: RuleKind,
    author_id: str,
    now: datetime,
) -> Rule:
    """Store a rule someone said, replacing any rule for the same scope, subject and item."""
    _check_may_change(uow, scope, subject_id, author_id, now)
    rule = Rule(
        rule_id,
        subject_id,
        normalize_item_name(item),
        kind,
        scope,
        author_id,
        RuleSource.STATED,
        now,
    )
    uow.rules.put(rule)
    uow.items.ensure(rule.item_key)
    return rule


def delete_rule(
    uow: UnitOfWork,
    *,
    scope: RuleScope,
    subject_id: str,
    item: str,
    by: str,
    now: datetime,
) -> Rule | None:
    """Drop the rule for (subject, item) in this scope, as in "Raj drinks milk now".

    Returns the deleted rule, or None if there was none.
    """
    _check_may_change(uow, scope, subject_id, by, now)
    rule = uow.rules.find(scope, subject_id, normalize_item_name(item))
    if rule is not None:
        uow.rules.delete(rule.id)
    return rule


def _check_may_change(
    uow: UnitOfWork, scope: RuleScope, subject_id: str, speaker_id: str, now: datetime
) -> None:
    """Everywhere rules: only the subject. Group rules: any current member. Notes: the owner."""
    match scope:
        case Everywhere():
            if speaker_id != subject_id:
                raise NotAllowedError("Only the person it's about can change that rule.")
        case GroupScope(group_id):
            if not _is_current_member(uow, group_id, speaker_id, now):
                raise NotAllowedError("Only members of this group can change its rules.")
        case NotesScope(owner_id):
            if speaker_id != owner_id:
                raise NotAllowedError("Only the person who wrote these notes can change them.")


def _is_current_member(uow: UnitOfWork, group_id: str, person_id: str, now: datetime) -> bool:
    return any(
        m.person_id == person_id and m.left_at is None and m.joined_at <= now
        for m in uow.memberships.for_group(group_id)
    )

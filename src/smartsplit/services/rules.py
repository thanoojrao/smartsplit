"""Stating and deleting rules, with who may do it where (SPEC section 6.2)."""

from datetime import datetime

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import ConversationKind, RuleKind, RuleSource
from smartsplit.domain.model import Rule
from smartsplit.domain.values import GroupScope, RuleScope
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.scopes import stated_rule_scope


def add_stated_rule(
    uow: UnitOfWork,
    *,
    rule_id: str,
    conversation_kind: ConversationKind,
    group_id: str | None,
    subject_id: str,
    item: str,
    kind: RuleKind,
    author_id: str,
    now: datetime,
) -> Rule:
    """Store a rule someone said, replacing any rule for the same scope, subject and item.

    The scope comes from where it was said and about whom (`stated_rule_scope`), so a group
    chat can never create someone's Everywhere rule.
    """
    scope = stated_rule_scope(conversation_kind, group_id, author_id, subject_id)
    _check_may_change(uow, scope, author_id, now)
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
    conversation_kind: ConversationKind,
    group_id: str | None,
    subject_id: str,
    item: str,
    by: str,
    now: datetime,
) -> Rule | None:
    """Drop the rule for (subject, item) in the scope of this chat, as in "Raj drinks milk now".

    Returns the deleted rule, or None if there was none.
    """
    scope = stated_rule_scope(conversation_kind, group_id, by, subject_id)
    _check_may_change(uow, scope, by, now)
    rule = uow.rules.find(scope, subject_id, normalize_item_name(item))
    if rule is not None:
        uow.rules.delete(rule.id)
    return rule


def _check_may_change(uow: UnitOfWork, scope: RuleScope, speaker_id: str, now: datetime) -> None:
    """Group rules: only current members. Everywhere rules and notes need no check here:
    `stated_rule_scope` only ever gives the speaker their own Everywhere rule or own notes."""
    if isinstance(scope, GroupScope) and not is_current_member(
        uow, scope.group_id, speaker_id, now
    ):
        raise NotAllowedError("Only members of this group can change its rules.")


def is_current_member(uow: UnitOfWork, group_id: str, person_id: str, now: datetime) -> bool:
    """A member at `now`: joined by then and not yet left."""
    return any(
        m.person_id == person_id and m.joined_at <= now and (m.left_at is None or m.left_at > now)
        for m in uow.memberships.for_group(group_id)
    )

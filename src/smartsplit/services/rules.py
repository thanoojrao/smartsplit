"""Stating and deleting rules, with who may do it where (SPEC section 6.2)."""

from datetime import datetime

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import ConversationKind, RuleKind, RuleSource
from smartsplit.domain.model import Rule
from smartsplit.domain.values import GroupScope, RuleScope
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.scopes import stated_rule_scope


def propose_stated_rule(
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
    """The rule as it would be stored, after the permission check; nothing is written, so a
    rule about someone else can be restated and confirmed first (SPEC 12.3).

    The scope comes from where it was said and about whom (`stated_rule_scope`), so a group
    chat can never create someone's Everywhere rule.
    """
    scope = stated_rule_scope(conversation_kind, group_id, author_id, subject_id)
    _check_may_change(uow, scope, author_id, now)
    return Rule(
        rule_id,
        subject_id,
        normalize_item_name(item),
        kind,
        scope,
        author_id,
        RuleSource.STATED,
        now,
    )


def put_rule(uow: UnitOfWork, rule: Rule) -> None:
    uow.rules.put(rule)
    uow.items.ensure(rule.item_key)


def find_stated_rule(
    uow: UnitOfWork,
    *,
    conversation_kind: ConversationKind,
    group_id: str | None,
    subject_id: str,
    item: str,
    by: str,
    now: datetime,
) -> Rule | None:
    """The rule `by` may delete from this chat, after the permission check (SPEC 6.2)."""
    scope = stated_rule_scope(conversation_kind, group_id, by, subject_id)
    _check_may_change(uow, scope, by, now)
    return uow.rules.find(scope, subject_id, normalize_item_name(item))


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

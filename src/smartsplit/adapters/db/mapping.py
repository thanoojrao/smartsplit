"""Column encodings shared by the Postgres stores."""

from smartsplit.domain.values import (
    Context,
    ConversationKey,
    Everywhere,
    GroupContext,
    GroupScope,
    LocalScope,
    NotesScope,
    PersonalContext,
    RuleScope,
)

_EVERYWHERE = "everywhere"
_GROUP = "group"
_NOTES = "notes"


def scope_columns(scope: RuleScope) -> tuple[str, str]:
    """(scope_kind, scope_ref), with '' as the ref of Everywhere."""
    match scope:
        case Everywhere():
            return _EVERYWHERE, ""
        case GroupScope(group_id):
            return _GROUP, group_id
        case NotesScope(owner_id):
            return _NOTES, owner_id


def scope_from(kind: str, ref: str) -> RuleScope:
    if kind == _EVERYWHERE:
        return Everywhere()
    return local_scope_from(kind, ref)


def local_scope_from(kind: str, ref: str) -> LocalScope:
    if kind == _GROUP:
        return GroupScope(ref)
    if kind == _NOTES:
        return NotesScope(ref)
    raise ValueError(f"unknown local scope kind {kind!r}")


def context_group_id(context: Context) -> str | None:
    """None stands for the personal-splits context."""
    return context.group_id if isinstance(context, GroupContext) else None


def context_from(group_id: str | None) -> Context:
    return PersonalContext() if group_id is None else GroupContext(group_id)


def key_from(channel: str, ref: str) -> ConversationKey:
    return ConversationKey(channel, ref)

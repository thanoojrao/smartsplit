"""Where a bill's matches, observations and stated rules live (SPEC sections 6.2, 6.4, 6.5)."""

from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.values import (
    Context,
    Everywhere,
    GroupContext,
    GroupScope,
    LocalScope,
    NotesScope,
    RuleScope,
)


def local_scope_for(context: Context, added_by: str) -> LocalScope:
    """Group bills learn and remember matches in the group; personal splits in the adder's notes."""
    if isinstance(context, GroupContext):
        return GroupScope(context.group_id)
    return NotesScope(added_by)


def stated_rule_scope(
    kind: ConversationKind, group_id: str | None, speaker_id: str, subject_id: str
) -> RuleScope:
    """The scope of a rule someone states, from where they say it and about whom.

    In a group chat it is always that group's rule, even about yourself. In your personal chat
    it is your Everywhere rule about yourself, or your notes about someone else.
    """
    if kind is ConversationKind.GROUP:
        if group_id is None:
            raise ValueError("a group chat needs its group")
        return GroupScope(group_id)
    if subject_id == speaker_id:
        return Everywhere()
    return NotesScope(speaker_id)

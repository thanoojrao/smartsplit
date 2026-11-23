"""Rules said in chat: adding, deleting and listing, with privacy (SPEC 6.2, 10.7, 12.3).

Your own rules apply at once. A rule about someone else, or deleting one, is restated and
needs a "yes" from the speaker first.
"""

from smartsplit.domain.commands import AddRule, Command, DeleteRule
from smartsplit.domain.enums import ConversationKind, PromptKind, RuleKind, RuleSource
from smartsplit.domain.model import Rule
from smartsplit.domain.prompts import ConfirmActionPayload, RuleChangeEffect
from smartsplit.domain.values import Everywhere, GroupScope, NotesScope
from smartsplit.services.names import Directory
from smartsplit.services.prompting import open_prompt
from smartsplit.services.rules import find_stated_rule, propose_stated_rule, put_rule
from smartsplit.services.text import name_for
from smartsplit.services.turn import Turn

RULE_VERSION = 0
"""Rule changes have no version to go stale: a "yes" re-applies the exact rule shown."""


def add_rule(turn: Turn, command: AddRule, directory: Directory) -> None:
    subject = _subject(turn, command.subject, directory)
    rule = propose_stated_rule(
        turn.uow,
        rule_id=turn.ids.new_id(),
        conversation_kind=turn.conversation.kind,
        group_id=turn.conversation.group_id,
        subject_id=subject,
        item=command.item,
        kind=command.kind,
        author_id=turn.speaker.id,
        now=turn.now,
    )
    said = describe(turn, rule)
    if subject == turn.speaker.id:
        put_rule(turn.uow, rule)
        turn.reply(f"Noted: {said}.")
        return
    _ask(turn, command, RuleChangeEffect(rule, None), f"Save this rule: {said}?")


def delete_rule(turn: Turn, command: DeleteRule, directory: Directory) -> None:
    subject = _subject(turn, command.subject, directory)
    rule = find_stated_rule(
        turn.uow,
        conversation_kind=turn.conversation.kind,
        group_id=turn.conversation.group_id,
        subject_id=subject,
        item=command.item,
        by=turn.speaker.id,
        now=turn.now,
    )
    if rule is None:
        turn.reply("There's no rule like that here.")
        return
    if subject == turn.speaker.id:
        turn.uow.rules.delete(rule.id)
        turn.reply(f"Removed: {describe(turn, rule)}.")
        return
    _ask(
        turn, command, RuleChangeEffect(None, rule.id), f"Remove this rule: {describe(turn, rule)}?"
    )


def apply_rule_change(turn: Turn, effect: RuleChangeEffect) -> None:
    """The confirmed change, exactly as restated; group changes are announced in the chat."""
    if effect.add is not None:
        put_rule(turn.uow, effect.add)
        turn.reply(f"{turn.speaker.display_name} saved a rule: {describe(turn, effect.add)}.")
        return
    rule = turn.uow.rules.get(effect.delete_rule_id or "")
    if rule is None:
        turn.reply("That rule is already gone.")
        return
    turn.uow.rules.delete(rule.id)
    turn.reply(f"{turn.speaker.display_name} removed a rule: {describe(turn, rule)}.")


def list_rules(turn: Turn, subject_said: str | None, directory: Directory) -> None:
    """In a group: only its rules here, and the full list in the asker's own chat (F13, F14)."""
    subject = _subject(turn, subject_said, directory)
    rules = turn.uow.rules.for_subjects([subject])
    group_id = turn.conversation.group_id
    if group_id is not None:
        here = [r for r in rules if r.scope == GroupScope(group_id)]
        turn.reply(_listing(turn, here, with_scope=False) or "No rules about that here.")
        visible = [r for r in rules if _visible(turn, r)]
        if len(visible) > len(here) and turn.direct(
            turn.speaker.id, _listing(turn, visible, with_scope=True)
        ):
            turn.reply("I sent you the full list in a DM.")
        return
    visible = [r for r in rules if _visible(turn, r)]
    turn.reply(_listing(turn, visible, with_scope=True) or "No rules about that yet.")


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
    match rule.scope:
        case Everywhere():
            return "everywhere"
        case GroupScope(group_id):
            group = turn.uow.groups.get(group_id)
            return group.name if group else "a group"
        case NotesScope():
            return "your notes"


def _visible(turn: Turn, rule: Rule) -> bool:
    """Your own everywhere rules, your notes, and rules of groups you are in."""
    me = turn.speaker.id
    match rule.scope:
        case Everywhere():
            return rule.subject_id == me
        case NotesScope(owner_id):
            return owner_id == me
        case GroupScope(group_id):
            return any(m.group_id == group_id for m in turn.uow.memberships.for_person(me))


def _viewer(turn: Turn) -> str | None:
    return None if turn.conversation.kind is ConversationKind.GROUP else turn.speaker.id


def _subject(turn: Turn, said: str | None, directory: Directory) -> str:
    if said is None:
        return turn.speaker.id
    return directory.resolve(said, turn.settings.default_region)


def _ask(turn: Turn, command: Command, effect: RuleChangeEffect, question: str) -> None:
    payload = ConfirmActionPayload(command, effect, RULE_VERSION)
    open_prompt(turn, None, PromptKind.CONFIRM_ACTION, payload, turn.speaker.id)
    turn.reply(f'{question} Say "yes" to confirm.')

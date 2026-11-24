"""Which code-rendered blocks a reply keeps (SPEC 8.5)."""

from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.model import Conversation
from smartsplit.domain.prompts import ChatRef
from smartsplit.domain.values import ConversationKey
from smartsplit.services.replies import latest_per_draft
from smartsplit.services.turn import Said

CHAT = Conversation(ConversationKey("cli", "flat"), ConversationKind.GROUP, "Flat 4B", "g1", None)


def block(text: str, *refs: ChatRef, summary_of: str | None = None) -> Said:
    return Said(CHAT, text, refs, summary_of=summary_of)


def summary(draft: str, version: int) -> Said:
    return block(f"{draft} v{version}", ChatRef("draft", draft, version), summary_of=draft)


def test_only_the_last_summary_of_a_draft_is_kept() -> None:
    first, second = summary("d1", 1), summary("d1", 2)
    assert latest_per_draft([first, second]) == [second]


def test_other_blocks_stay_in_order() -> None:
    details = block("d1 details", ChatRef("draft", "d1", 2))
    saved = block("Saved: Toit", ChatRef("bill", "b1"))
    other = summary("d2", 1)
    balances = block("Sam owes Alex 300")
    shown = [summary("d1", 1), details, other, summary("d1", 2), saved, balances]
    assert latest_per_draft(shown) == [details, other, summary("d1", 2), saved, balances]


def test_a_summary_before_details_is_kept() -> None:
    # "split this and show me the lines": both were asked for
    shown = [summary("d1", 1), block("d1 details", ChatRef("draft", "d1", 1))]
    assert latest_per_draft(shown) == shown


def test_details_of_a_version_that_changed_later_are_dropped() -> None:
    stale = block("d1 details", ChatRef("draft", "d1", 1))
    shown = [stale, summary("d1", 2)]
    assert latest_per_draft(shown) == [summary("d1", 2)]

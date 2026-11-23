"""Enumerations of the domain (CONTRACTS section 1.1). Values are the lowercase names."""

from enum import StrEnum


class RuleKind(StrEnum):
    """How a member relates to an item key (SPEC section 5)."""

    EXCLUDE = "exclude"
    """Never charge this member for the item."""
    SOFT_EXCLUDE = "soft_exclude"
    """Member usually doesn't use it: include them, but ask."""
    ONLY = "only"
    """Item belongs only to the member(s) holding this rule."""


class QuestionReason(StrEnum):
    """Why the split engine wants a human to confirm an item."""

    SOFT_RULE = "soft_rule"
    NO_ELIGIBLE_MEMBERS = "no_eligible_members"


class RuleSource(StrEnum):
    STATED = "stated"
    LEARNED = "learned"


class ConversationKind(StrEnum):
    GROUP = "group"
    PERSONAL = "personal"


class DraftState(StrEnum):
    """Bill draft lifecycle (SPEC section 10.4)."""

    QUEUED = "queued"
    AWAITING_PEOPLE = "awaiting_people"
    REVIEWING = "reviewing"
    SAVED = "saved"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PromptKind(StrEnum):
    """What code tracks for the bot (SPEC 4.5); the model's own questions are in the transcript."""

    ENGINE_QUESTION = "engine_question"
    PENDING_ACTION = "pending_action"


class PromptStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    DROPPED = "dropped"


class SettlementKind(StrEnum):
    PAYMENT = "payment"
    SQUARE_UP = "square_up"


class AnswerOutcome(StrEnum):
    """What a saved bill showed about one person and one item (SPEC section 6.5)."""

    EXCLUDED = "excluded"
    SOLE_ASSIGNEE = "sole_assignee"
    INCLUDED = "included"


class MatchHow(StrEnum):
    """How a receipt line got its item key (SPEC section 6.4)."""

    EXACT = "exact"
    ALIAS = "alias"
    FUZZY = "fuzzy"
    LLM = "llm"
    NONE = "none"


class NotificationKind(StrEnum):
    BILL_ADDED = "bill_added"
    BILL_CHANGED = "bill_changed"
    PAYMENT_RECORDED = "payment_recorded"
    PAYMENT_REVERSED = "payment_reversed"
    SQUARE_UP = "square_up"
    REMINDER = "reminder"


class PhotoOutcome(StrEnum):
    """What reading one inbound photo found (SPEC 7)."""

    RECEIPT = "receipt"
    NOT_A_RECEIPT = "not_a_receipt"
    UNREADABLE = "unreadable"

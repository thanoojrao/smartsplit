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
    PARSING = "parsing"
    REVIEWING = "reviewing"
    SAVED = "saved"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_DRAFT_STATES = frozenset({DraftState.SAVED, DraftState.CANCELLED, DraftState.EXPIRED})


class PromptKind(StrEnum):
    ENGINE_QUESTION = "engine_question"
    WHO_WITH = "who_with"
    WHICH_PERSON = "which_person"
    NEED_CONTACT = "need_contact"
    CONFIRM_TOTAL = "confirm_total"
    CONFIRM_LINE = "confirm_line"
    CONFIRM_ACTION = "confirm_action"
    JOIN_GROUP = "join_group"
    DUPLICATE_WARNING = "duplicate_warning"


class PromptStatus(StrEnum):
    PENDING = "pending"
    """Not asked yet, e.g. a later batch of questions."""
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
    REQUESTED_REPLY = "requested_reply"

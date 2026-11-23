"""Errors the storage port raises; both the fake and the Postgres adapter use them.

On Postgres a constraint error also aborts the transaction, so catch it outside the unit of
work (the fake would let you carry on, which real code must not rely on).
"""


class ConstraintViolationError(Exception):
    """A write broke a storage rule; both the fake and Postgres raise these subclasses."""


class DuplicateKeyError(ConstraintViolationError):
    """A record with this key (id, phone, chat, current membership, ...) already exists."""


class MissingReferenceError(ConstraintViolationError):
    """The record points at a person or group that doesn't exist."""


class InvalidRecordError(ConstraintViolationError):
    """The record breaks a check, e.g. a conversation with both a group and a person."""


class ChatBusyError(Exception):
    """The conversation lock wasn't free in time (HTTP 503, the gateway retries)."""


class StaleDraftError(Exception):
    """The draft's state changed since it was read (e.g. expired by `tick` meanwhile)."""

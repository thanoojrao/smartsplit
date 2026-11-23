"""Errors services raise; a tool turns them into a short reason for the model (CONTRACTS 6)."""


class NotAllowedError(Exception):
    """The speaker may not do this, or it can't be done; the message is a short plain reason."""

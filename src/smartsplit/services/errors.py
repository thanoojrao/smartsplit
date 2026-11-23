"""Errors services raise for the orchestrator to turn into chat replies (CONTRACTS section 6)."""


class NotAllowedError(Exception):
    """The speaker may not do this; the message is a short plain refusal for the chat."""

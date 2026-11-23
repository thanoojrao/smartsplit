"""Errors services raise for the orchestrator to turn into chat replies (CONTRACTS section 6)."""

from smartsplit.domain.values import PersonRef


class NotAllowedError(Exception):
    """The speaker may not do this; the message is a short plain refusal for the chat."""


class NeedsClarificationError(Exception):
    """The name can't be resolved yet; the orchestrator turns this into a prompt."""

    def __init__(self, said: PersonRef, candidate_ids: tuple[str, ...]) -> None:
        super().__init__(said)
        self.said = said
        self.candidate_ids = candidate_ids
        """Empty: unknown, ask for a contact. Several: ask which one."""

"""What a tool that needs a "yes" computes before asking (SPEC 8.4)."""

from dataclasses import dataclass

from smartsplit.domain.prompts import Effect


@dataclass(frozen=True, slots=True)
class Proposal:
    """The exact effect, the version of the data it was computed on, and its restatement."""

    effect: Effect
    version: int
    restatement: str

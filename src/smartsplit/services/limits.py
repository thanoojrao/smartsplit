"""The daily limits on model calls (SPEC 12.5).

Over the speaker's own limit or the install's, the bot says so once a day per person,
without calling the model, and is silent after that until tomorrow (install timezone).
"""

from dataclasses import dataclass
from datetime import date

from smartsplit.domain.model import INSTALL_COUNTER
from smartsplit.ports.repository import Repository, UnitOfWork
from smartsplit.services.turn import OrchestratorSettings

WARN_AT = 0.8
"""Share of the install's daily calls at which a warning is logged."""


@dataclass(frozen=True, slots=True)
class Allowance:
    over: bool
    """No model calls for this message."""
    install_nearly_spent: bool


def allowance(
    uow: UnitOfWork, person_id: str | None, day: date, settings: OrchestratorSettings
) -> Allowance:
    install = _calls(uow, INSTALL_COUNTER, day)
    mine = _calls(uow, person_id, day) if person_id else 0
    over = install >= settings.llm_calls_per_day or (
        person_id is not None and mine >= settings.llm_calls_per_person_per_day
    )
    return Allowance(over, install >= WARN_AT * settings.llm_calls_per_day)


def first_notice_today(repository: Repository, person_id: str, day: date) -> bool:
    """Count the "limit reached" notice; True only for the first one today."""
    return repository.count_usage(f"{NOTICE_PREFIX}{person_id}", day) == 1


NOTICE_PREFIX = "limit-notice:"
"""A usage counter that counts notices, not model calls (DECISIONS M11)."""


def _calls(uow: UnitOfWork, counter: str, day: date) -> int:
    usage = uow.llm_usage.get(counter, day)
    return usage.calls if usage else 0

"""Collect every model call's token usage during a live run and print a summary at the end:
usage and estimated cost per model and purpose, then each scenario's messages, questions and
result, and the cost per chat message."""

import logging
import os
from collections import defaultdict
from collections.abc import Callable

import pytest

from tests.live.report import SCENARIOS

PRICES_PER_MTOK = {
    "claude-haiku-5-5": {"input": 0.10, "cache_read": 0.01, "cache_write": 0.125, "output": 0.50},
    "claude-sonnet-5-5": {"input": 2.0, "cache_read": 0.10, "cache_write": 2.5, "output": 10.0},
}
"""List prices in USD for prompts up to 100K tokens (5-minute cache writes); an estimate only."""
FIELDS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.calls: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.calls.append({k: record.__dict__.get(k) for k in ("purpose", "model", *FIELDS)})


_collector = _Collector()
_outcomes: dict[str, str] = {}


def pytest_configure(config: pytest.Config) -> None:
    logger = logging.getLogger("smartsplit.llm")
    logger.setLevel(logging.INFO)
    logger.addHandler(_collector)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or report.outcome != "passed":
        _outcomes[report.nodeid.rsplit("::", 1)[-1]] = report.outcome


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Only for live runs: other tests' scripted calls aren't real usage."""
    if os.environ.get("SMARTSPLIT_LIVE_LLM") != "1" or not _collector.calls:
        return
    write = terminalreporter.write_line
    totals: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: dict.fromkeys(("calls", *FIELDS), 0)
    )
    for call in _collector.calls:
        row = totals[(_model(call["model"]), str(call["purpose"]))]
        row["calls"] += 1
        for field in FIELDS:
            value = call[field]
            row[field] += value if isinstance(value, int) else 0
    write("")
    write("model usage:")
    heads = ("calls", "input", "cache rd", "cache wr", "output", "~USD")
    widths = (6, 9, 10, 10, 9, 9)
    write(
        "model / purpose".ljust(34)
        + "".join(h.rjust(w) for h, w in zip(heads, widths, strict=True))
    )
    grand = chat = 0.0
    for (model, purpose), row in sorted(totals.items()):
        cost = _cost(model, row)
        grand += cost or 0.0
        chat += (cost or 0.0) if purpose != "receipt" else 0.0
        shown = f"{cost:>9.4f}" if cost is not None else "  no price"
        write(
            f"{model + ' / ' + purpose:<34}{row['calls']:>6}{row['input_tokens']:>9}"
            f"{row['cache_read_tokens']:>10}{row['cache_write_tokens']:>10}"
            f"{row['output_tokens']:>9}{shown}"
        )
    write(f"{'total':<34}{len(_collector.calls):>6}{'':>38}{grand:>9.4f}  (estimate)")
    _scenarios(write, chat)


def _scenarios(write: Callable[[str], object], chat_cost: float) -> None:
    if not SCENARIOS:
        return
    write("")
    write("scenarios:".ljust(52) + "messages".rjust(9) + "asked".rjust(7) + "  result")
    messages = 0
    for name, log in SCENARIOS.items():
        messages += log.messages
        outcome = _outcomes.get(name, "?")
        write(f"{name:<52}{log.messages:>9}{log.asked:>7}  {outcome}")
        if outcome != "passed" or os.environ.get("SMARTSPLIT_LIVE_VERBOSE") == "1":
            for line in log.lines:
                write(f"    {line}")
    if messages:
        write(f"chat cost per message: ~${chat_cost / messages:.4f} over {messages} messages")


def _model(raw: object) -> str:
    """The API may answer with a dated id; prices are by family."""
    name = str(raw)
    return next((known for known in PRICES_PER_MTOK if name.startswith(known)), name)


def _cost(model: str, row: dict[str, int]) -> float | None:
    """None for a model with no price here (the totals then leave it out)."""
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    return (
        row["input_tokens"] * prices["input"]
        + row["cache_read_tokens"] * prices["cache_read"]
        + row["cache_write_tokens"] * prices["cache_write"]
        + row["output_tokens"] * prices["output"]
    ) / 1_000_000

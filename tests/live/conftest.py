"""Collect every model call's token usage during a live run and print a summary at the end."""

import logging
import os
from collections import defaultdict

import pytest

PRICES_PER_MTOK = {"input": 2.0, "cache_read": 0.10, "cache_write": 2.5, "output": 10.0}
"""Claude Sonnet 5.5 list prices in USD (5-minute cache writes); an estimate only."""
FIELDS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.calls: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.calls.append({k: record.__dict__.get(k) for k in ("purpose", "model", *FIELDS)})


_collector = _Collector()


def pytest_configure(config: pytest.Config) -> None:
    logger = logging.getLogger("smartsplit.llm")
    logger.setLevel(logging.INFO)
    logger.addHandler(_collector)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Only for live runs: other tests' scripted calls aren't real usage."""
    if os.environ.get("SMARTSPLIT_LIVE_LLM") != "1" or not _collector.calls:
        return
    totals: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(("calls", *FIELDS), 0))
    for call in _collector.calls:
        row = totals[str(call["purpose"])]
        row["calls"] += 1
        for field in FIELDS:
            value = call[field]
            row[field] += value if isinstance(value, int) else 0
    write = terminalreporter.write_line
    write("")
    write(f"model usage ({_collector.calls[0]['model']}):")
    heads = ("calls", "input", "cache rd", "cache wr", "output", "~USD")
    widths = (6, 9, 10, 10, 9, 9)
    write("purpose".ljust(14) + "".join(h.rjust(w) for h, w in zip(heads, widths, strict=True)))
    grand = 0.0
    for purpose, row in sorted(totals.items()):
        cost = _cost(row)
        grand += cost
        write(
            f"{purpose:<14}{row['calls']:>6}{row['input_tokens']:>9}{row['cache_read_tokens']:>10}"
            f"{row['cache_write_tokens']:>10}{row['output_tokens']:>9}{cost:>9.4f}"
        )
    write(f"{'total':<14}{len(_collector.calls):>6}{'':>38}{grand:>9.4f}  (estimate)")


def _cost(row: dict[str, int]) -> float:
    return (
        row["input_tokens"] * PRICES_PER_MTOK["input"]
        + row["cache_read_tokens"] * PRICES_PER_MTOK["cache_read"]
        + row["cache_write_tokens"] * PRICES_PER_MTOK["cache_write"]
        + row["output_tokens"] * PRICES_PER_MTOK["output"]
    ) / 1_000_000

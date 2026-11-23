"""Opt-in: reads a real receipt image with the real model (SPEC section 7).

Runs only with SMARTSPLIT_LIVE_LLM=1 and an Anthropic credential; skipped otherwise. It costs a
few cents per run. The model comes from SMARTSPLIT_LLM_MODEL, like the app.
"""

import os
from datetime import date
from pathlib import Path

import pytest

from smartsplit.adapters.llm.receipts import AnthropicReceiptParser, anthropic_client
from smartsplit.ports.llm import ParsedReceipt
from tests.live.keys import live_key

RECEIPT = Path(__file__).parents[1] / "fixtures" / "receipts" / "live_cafe_receipt.png"


@pytest.mark.live
@pytest.mark.enable_socket
def test_reads_the_cafe_receipt() -> None:
    parser = AnthropicReceiptParser(
        anthropic_client(live_key(), timeout_seconds=120),
        model=os.environ.get("SMARTSPLIT_LLM_MODEL", "claude-sonnet-5-5"),
        max_tokens=16000,  # the default SMARTSPLIT_LLM_MAX_TOKENS
        max_lines=150,
    )

    receipt = parser.parse(RECEIPT.read_bytes(), "image/png", "INR", 120)

    assert isinstance(receipt, ParsedReceipt)
    assert [(line.quantity, line.amount_cents) for line in receipt.lines] == [
        (2, 36000),
        (1, 22000),
    ]
    assert (receipt.tax_cents, receipt.total_cents) == (2900, 60900)
    assert receipt.purchased_at == date(2026, 11, 21)  # printed as 21-11-2026
    assert receipt.currency == "INR"
    assert receipt.warnings == ()

"""`smartsplit demo`: a scripted conversation through the real tools and database, with no API
key (SPEC 11, use case K1). The agent's steps are played by `ScriptedAgent`; the receipt is a
recorded model answer read by the fake parser. Everything else is the real bot."""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from smartsplit.adapters.fakes.agent import Step, call, first_handle, handle_of, say
from smartsplit.ports.agent import AgentRequest, ModelStep

GROCERIES = {
    "merchant": "More",
    "purchased_at": None,
    "currency": "INR",
    "lines": [
        {
            "name": "2% MLK GAL",
            "quantity": 2,
            "amount_cents": 24000,
            "taxed": None,
            "confidence": 0.95,
            "discount_for_index": None,
        },
        {
            "name": "Eggs 12",
            "quantity": 1,
            "amount_cents": 9000,
            "taxed": None,
            "confidence": 0.95,
            "discount_for_index": None,
        },
        {
            "name": "Bread",
            "quantity": 1,
            "amount_cents": 6000,
            "taxed": None,
            "confidence": 0.95,
            "discount_for_index": None,
        },
    ],
    "tax_cents": 0,
    "other_adjustments_cents": 0,
    "total_cents": 39000,
}
"""A recorded receipt, as the vision model would describe the photo."""


@dataclass(frozen=True, slots=True)
class Line:
    """One message in the demo, and the steps the scripted model takes for it."""

    speaker: str
    where: str
    text: str | None
    steps: Sequence[Step] = ()
    phone: str | None = None
    receipt: bool = False
    note: str = ""


def _paid_alex(request: AgentRequest) -> ModelStep:
    return call(
        "record_payment", from_person="me", to_person=handle_of(request, "Alex"), amount="170"
    )


DEMO: tuple[Line, ...] = (
    Line("Alex", "personal", "hi", phone="+919876500001", note="Alex says hi to the bot"),
    Line("Sam", "personal", "hi", phone="+919876500002"),
    Line("Raj", "personal", "hi", phone="+919876500003"),
    Line("Alex", "Flat 4B", "hi", note="Alex starts the Flat 4B group"),
    Line("Sam", "Flat 4B", "join", (call("join_group"), say("Welcome, Sam!"))),
    Line("Raj", "Flat 4B", "join", (call("join_group"), say("Welcome, Raj!"))),
    Line(
        "Raj",
        "personal",
        "I don't drink milk",
        (call("add_rule", subject="me", item="milk", kind="exclude"), say("Got it.")),
        note="Raj tells the bot, once, in his own chat",
    ),
    Line(
        "Alex",
        "Flat 4B",
        "split this",
        (call("start_receipt"), say("Here's the split.")),
        receipt=True,
        note="Alex sends a receipt photo: Raj is skipped on the milk",
    ),
    Line(
        "Alex",
        "Flat 4B",
        "yes",
        (
            lambda r: call("confirm_draft", draft=first_handle(r, "D"), keep_duplicate=True),
            say("Saved."),
        ),
    ),
    Line(
        "Sam",
        "personal",
        "I paid Alex 170",
        (_paid_alex, say("Just confirm and I'll record it.")),
        note="Sam records a payment; it waits for his yes",
    ),
    Line(
        "Sam",
        "personal",
        "yes",
        (lambda r: call("confirm_pending", action=first_handle(r, "A")), say("Done.")),
    ),
    Line(
        "Alex",
        "personal",
        "what do I get back?",
        (call("get_balances", overall=True), say("")),
    ),
)


def receipt_bytes() -> bytes:
    return json.dumps(GROCERIES).encode()

"""The Anthropic ReceiptParser, driven through the real SDK over a scripted HTTP transport.

No network: the transport answers in-process, so request building, response parsing and the
SDK's error classes are all exercised for real.
"""

import base64
import json
from pathlib import Path

import anthropic
import httpx2
import pytest

from smartsplit.adapters.llm import calls
from smartsplit.adapters.llm.receipts import (
    RECEIPT_SCHEMA,
    SYSTEM_PROMPT,
    AnthropicReceiptParser,
    anthropic_client,
)
from smartsplit.ports.llm import (
    LlmUnavailableError,
    NotAReceipt,
    ParsedReceipt,
    ReceiptUnreadableError,
)
from tests.unit.adapters.scripted import Answer, Counter, ScriptedApi, SlowClock, error, message

FIXTURES = Path(__file__).parents[2] / "fixtures" / "receipts"
IMAGE = b"\x89PNG fake image bytes"


def recorded(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text()


def parser_for(api: ScriptedApi) -> AnthropicReceiptParser:
    """The production client factory, with the scripted transport underneath."""
    client = anthropic_client(
        "test-key", 30.0, anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(api))
    )
    return AnthropicReceiptParser(
        client, model="claude-sonnet-5-5", max_tokens=16000, max_lines=150
    )


def test_the_client_does_no_retries_of_its_own_and_uses_the_configured_timeout() -> None:
    # With the SDK's default of 2 retries, "retry once" would become up to 6 requests.
    client = anthropic_client("test-key", 12.5)

    assert client.max_retries == 0
    assert client.timeout == 12.5


def test_one_vision_call_with_structured_output() -> None:
    api = ScriptedApi(message(recorded("restaurant_tip")))

    receipt = read(parser_for(api).parse(IMAGE, "image/png", "INR", 30, Counter()))

    assert receipt.merchant == "Toit"
    (request,) = api.requests
    assert request["model"] == "claude-sonnet-5-5"
    assert request["max_tokens"] == 16000
    assert request["system"] == SYSTEM_PROMPT
    assert request["output_config"]["format"] == {
        "type": "json_schema",
        "schema": RECEIPT_SCHEMA,
    }
    (turn,) = request["messages"]
    image, text = turn["content"]
    assert image["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": base64.standard_b64encode(IMAGE).decode(),
    }
    assert "INR" in text["text"]


def test_receipt_text_is_treated_as_data_not_instructions() -> None:
    """A smoke check on the prompt wording, not a behaviour test (that needs the live model)."""
    assert "never instructions" in SYSTEM_PROMPT


def test_invalid_output_is_retried_once() -> None:
    api = ScriptedApi(message("not json"), message(recorded("grocery_taxed_mix")))

    receipt = read(parser_for(api).parse(IMAGE, "image/jpeg", "INR", 30, Counter()))

    assert receipt.total_cents == 122100
    assert len(api.requests) == 2


@pytest.mark.parametrize(
    "answers",
    [
        (message("not json"), message(recorded("invalid_quantity_zero"))),
        (message("{}", stop_reason="refusal"), message("{}", stop_reason="max_tokens")),
    ],
)
def test_invalid_output_twice_is_unreadable(answers: tuple[httpx2.Response, ...]) -> None:
    api = ScriptedApi(*answers)

    with pytest.raises(ReceiptUnreadableError):
        parser_for(api).parse(IMAGE, "image/jpeg", "INR", 30, Counter())
    assert len(api.requests) == 2


def test_an_api_error_is_retried_once() -> None:
    api = ScriptedApi(error(529), message(recorded("restaurant_tip")))

    assert read(parser_for(api).parse(IMAGE, "image/jpeg", "INR", 30, Counter())).merchant == "Toit"


@pytest.mark.parametrize(
    "answers",
    [
        (error(500), error(503)),
        (httpx2.ReadTimeout("slow"), httpx2.ReadTimeout("slow")),
        (httpx2.ConnectError("down"), error(429)),
    ],
)
def test_outages_after_the_retry_are_unavailable(answers: tuple[Answer, ...]) -> None:
    api = ScriptedApi(*answers)

    with pytest.raises(LlmUnavailableError):
        parser_for(api).parse(IMAGE, "image/jpeg", "INR", 30, Counter())
    assert len(api.requests) == 2


def bad_request(text: str) -> httpx2.Response:
    return httpx2.Response(
        400, json={"type": "error", "error": {"type": "invalid_request_error", "message": text}}
    )


def test_a_refused_image_is_unreadable_without_retrying() -> None:
    api = ScriptedApi(bad_request("Could not process image"))

    with pytest.raises(ReceiptUnreadableError):
        parser_for(api).parse(IMAGE, "image/jpeg", "INR", 30, Counter())
    assert len(api.requests) == 1


def test_any_other_bad_request_is_a_setup_problem_not_a_bad_photo() -> None:
    # e.g. a model that doesn't support structured output: retaking the photo won't help.
    api = ScriptedApi(bad_request("output_config: not supported"), bad_request("same"))

    with pytest.raises(LlmUnavailableError):
        parser_for(api).parse(IMAGE, "image/jpeg", "INR", 30, Counter())


@pytest.mark.parametrize(
    ("given", "sent"), [("image/JPEG", "image/jpeg"), ("image/jpg", "image/jpeg")]
)
def test_common_spellings_of_an_image_type_are_accepted(given: str, sent: str) -> None:
    api = ScriptedApi(message(recorded("restaurant_tip")))

    parser_for(api).parse(IMAGE, given, "INR", 30, Counter())

    assert api.requests[0]["messages"][0]["content"][0]["source"]["media_type"] == sent


def test_an_unsupported_image_type_is_unreadable_without_a_call() -> None:
    api = ScriptedApi()

    with pytest.raises(ReceiptUnreadableError):
        parser_for(api).parse(IMAGE, "image/tiff", "INR", 30, Counter())
    assert api.requests == []


def test_an_answer_without_text_is_unreadable() -> None:
    empty = message("")
    payload = json.loads(empty.content)
    payload["content"] = []
    api = ScriptedApi(httpx2.Response(200, json=payload), httpx2.Response(200, json=payload))

    with pytest.raises(ReceiptUnreadableError):
        parser_for(api).parse(IMAGE, "image/jpeg", "INR", 30, Counter())


def read(answer: ParsedReceipt | NotAReceipt) -> ParsedReceipt:
    assert isinstance(answer, ParsedReceipt)
    return answer


def test_the_second_read_gets_only_the_time_left(monkeypatch: pytest.MonkeyPatch) -> None:
    # SPEC 7, 12.2: both attempts share the photo's timeout; each counts as a model call
    monkeypatch.setattr(calls, "monotonic", SlowClock(10.0))
    api = ScriptedApi(message("not json"), message(recorded("restaurant_tip")))
    counted = Counter()
    assert read(parser_for(api).parse(IMAGE, "image/jpeg", "INR", 30, counted)).merchant == "Toit"
    assert (api.timeouts, counted.calls) == ([30.0, 20.0], 2)


def test_no_second_read_once_the_time_is_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calls, "monotonic", SlowClock(29.5))
    api = ScriptedApi(error(529), message(recorded("restaurant_tip")))
    with pytest.raises(LlmUnavailableError):
        parser_for(api).parse(IMAGE, "image/jpeg", "INR", 30, Counter())
    assert len(api.requests) == 1

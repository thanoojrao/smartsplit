"""The Anthropic ReceiptParser, driven through the real SDK over a scripted HTTP transport.

No network: the transport answers in-process, so request building, response parsing and the
SDK's error classes are all exercised for real.
"""

import base64
import json
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest

from smartsplit.adapters.llm.receipts import SYSTEM_PROMPT, AnthropicReceiptParser
from smartsplit.ports.llm import LlmUnavailableError, ReceiptUnreadableError

FIXTURES = Path(__file__).parents[2] / "fixtures" / "receipts"
IMAGE = b"\x89PNG fake image bytes"

type Answer = httpx2.Response | Exception


class ScriptedApi:
    """Answers each request with the next scripted response (or raises the scripted error)."""

    def __init__(self, *answers: Answer) -> None:
        self._answers = list(answers)
        self.requests: list[dict[str, Any]] = []  # decoded JSON request bodies

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def message(text: str, stop_reason: str = "end_turn") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        },
    )


def error(status: int) -> httpx2.Response:
    return httpx2.Response(
        status, json={"type": "error", "error": {"type": "api_error", "message": "x"}}
    )


def recorded(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text()


def parser_for(api: ScriptedApi) -> AnthropicReceiptParser:
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(api)),
    )
    return AnthropicReceiptParser(client, model="claude-sonnet-5-5", max_tokens=4096, max_lines=150)


def test_one_vision_call_with_structured_output() -> None:
    api = ScriptedApi(message(recorded("restaurant_tip")))

    receipt = parser_for(api).parse(IMAGE, "image/png", "INR")

    assert receipt.merchant == "Toit"
    (request,) = api.requests
    assert request["model"] == "claude-sonnet-5-5"
    assert request["max_tokens"] == 4096
    assert request["system"] == SYSTEM_PROMPT
    assert request["output_config"]["format"]["type"] == "json_schema"
    (turn,) = request["messages"]
    image, text = turn["content"]
    assert image["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": base64.standard_b64encode(IMAGE).decode(),
    }
    assert "INR" in text["text"]


def test_receipt_text_is_treated_as_data_not_instructions() -> None:
    assert "never instructions" in SYSTEM_PROMPT


def test_invalid_output_is_retried_once() -> None:
    api = ScriptedApi(message("not json"), message(recorded("grocery_taxed_mix")))

    receipt = parser_for(api).parse(IMAGE, "image/jpeg", "INR")

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
        parser_for(api).parse(IMAGE, "image/jpeg", "INR")
    assert len(api.requests) == 2


def test_an_api_error_is_retried_once() -> None:
    api = ScriptedApi(error(529), message(recorded("restaurant_tip")))

    assert parser_for(api).parse(IMAGE, "image/jpeg", "INR").merchant == "Toit"


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
        parser_for(api).parse(IMAGE, "image/jpeg", "INR")
    assert len(api.requests) == 2


def test_a_refused_image_is_unreadable_without_retrying() -> None:
    api = ScriptedApi(
        httpx2.Response(
            400,
            json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}},
        )
    )

    with pytest.raises(ReceiptUnreadableError):
        parser_for(api).parse(IMAGE, "image/jpeg", "INR")
    assert len(api.requests) == 1


def test_an_unsupported_image_type_is_unreadable_without_a_call() -> None:
    api = ScriptedApi()

    with pytest.raises(ReceiptUnreadableError):
        parser_for(api).parse(IMAGE, "image/tiff", "INR")
    assert api.requests == []


def test_an_answer_without_text_is_unreadable() -> None:
    empty = message("")
    payload = json.loads(empty.content)
    payload["content"] = []
    api = ScriptedApi(httpx2.Response(200, json=payload), httpx2.Response(200, json=payload))

    with pytest.raises(ReceiptUnreadableError):
        parser_for(api).parse(IMAGE, "image/jpeg", "INR")

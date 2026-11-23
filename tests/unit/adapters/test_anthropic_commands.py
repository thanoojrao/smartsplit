"""The Anthropic CommandInterpreter through the real SDK over a scripted transport (SPEC 8)."""

import json
from datetime import date
from typing import Any, cast

import anthropic
import httpx2
import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartsplit.adapters.llm.command_tools import COMMAND_CLASSES, command_tools
from smartsplit.adapters.llm.commands import SYSTEM_PROMPT, AnthropicCommandInterpreter
from smartsplit.adapters.llm.receipts import anthropic_client
from smartsplit.domain.codec import encode
from smartsplit.domain.commands import Command, RecordPayment, Unknown
from smartsplit.domain.enums import ConversationKind
from smartsplit.ports.llm import InterpretContext, LlmUnavailableError, NameablePerson
from tests.unit.adapters.test_anthropic_receipts import ScriptedApi, error

CONTEXT = InterpretContext(
    conversation_kind=ConversationKind.PERSONAL,
    conversation_name=None,
    today=date(2026, 11, 23),
    speaker_id="me",
    nameable=(NameablePerson("p1", ("Sam", "Samuel")),),
    group_member_names=(),
    group_names=("Flat 4B",),
    open_prompts=(),
    draft_lines=(),
)


def reply(content: list[dict[str, Any]], stop_reason: str = "tool_use") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        },
    )


def tool_call(name: str, arguments: dict[str, Any]) -> httpx2.Response:
    return reply([{"type": "tool_use", "id": "toolu_1", "name": name, "input": arguments}])


def interpreter_for(api: ScriptedApi) -> AnthropicCommandInterpreter:
    client = anthropic_client(
        "test-key", 30.0, anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(api))
    )
    return AnthropicCommandInterpreter(client, model="claude-sonnet-5-5", max_tokens=16000)


def as_tool_call(command: Command) -> tuple[str, dict[str, Any]]:
    encoded = cast("dict[str, Any]", encode(command))
    return encoded.pop("type"), encoded


def test_one_request_with_every_command_as_a_strict_tool_and_untrusted_context() -> None:
    api = ScriptedApi(tool_call(*as_tool_call(RecordPayment(50000, payee="Sam"))))

    command = interpreter_for(api).interpret("paid Sam 500", CONTEXT)

    assert command == RecordPayment(50000, payee="Sam")
    (request,) = api.requests
    assert [tool["name"] for tool in request["tools"]] == [c.__name__ for c in COMMAND_CLASSES]
    assert all(tool["strict"] for tool in request["tools"])
    assert "tool_choice" not in request  # forced tool use returns 400 on current models
    assert request["system"][0]["text"] == SYSTEM_PROMPT
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    prompt = request["messages"][0]["content"]
    assert "<message>paid Sam 500</message>" in prompt
    assert '"Samuel"' in prompt


def test_no_tool_call_or_a_refusal_is_unknown() -> None:
    api = ScriptedApi(
        reply([{"type": "text", "text": "Hi!"}], stop_reason="end_turn"),
        reply([{"type": "text", "text": ""}], stop_reason="refusal"),
    )
    interpreter = interpreter_for(api)

    assert interpreter.interpret("hi bot", CONTEXT) == Unknown("hi bot")
    assert interpreter.interpret("hi bot", CONTEXT) == Unknown("hi bot")


@pytest.mark.parametrize(
    "call",
    [
        ("RecordPayment", {"amount": "lots", "payer": None, "payee": "Sam", "context_name": None}),
        ("NoSuchCommand", {}),
        ("Remind", {}),
    ],
)
def test_an_invalid_tool_call_is_unknown(call: tuple[str, dict[str, Any]]) -> None:
    api = ScriptedApi(tool_call(*call))

    assert interpreter_for(api).interpret("x", CONTEXT) == Unknown("x")


def test_an_outage_after_the_retry_is_unavailable() -> None:
    api = ScriptedApi(error(529), httpx2.ConnectError("down"))

    with pytest.raises(LlmUnavailableError):
        interpreter_for(api).interpret("paid Sam 500", CONTEXT)
    assert len(api.requests) == 2


@given(st.from_type(cast("type[object]", Command)))
def test_every_command_round_trips_through_its_tool(command: object) -> None:
    name, arguments = as_tool_call(cast("Command", command))
    api = ScriptedApi(tool_call(name, json.loads(json.dumps(arguments))))

    assert interpreter_for(api).interpret("x", CONTEXT) == command


def walk(schema: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            found.append(schema)
        for value in schema.values():
            found += walk(value)
    elif isinstance(schema, list):
        for value in schema:
            found += walk(value)
    return found


def test_tool_schemas_meet_strict_mode_rules() -> None:
    # Every object closes its properties and requires all of them (optional ones are nullable).
    for tool in command_tools():
        for obj in walk(tool["input_schema"]):
            assert obj["additionalProperties"] is False
            assert obj["required"] == list(obj["properties"])


def test_canonicalize_returns_a_known_or_new_key() -> None:
    api = ScriptedApi(
        reply([{"type": "text", "text": '{"item_key": "Milk "}'}], stop_reason="end_turn"),
        reply([{"type": "text", "text": "not json"}], stop_reason="end_turn"),
    )
    interpreter = interpreter_for(api)

    assert interpreter.canonicalize("2% MLK GAL", ["milk"]) == "milk"
    assert interpreter.canonicalize("Dragon  Fruit", ["milk"]) == "dragon fruit"
    format_config = api.requests[0]["output_config"]["format"]
    assert format_config["schema"]["required"] == ["item_key"]
    assert '"2% MLK GAL"' in api.requests[0]["messages"][0]["content"]

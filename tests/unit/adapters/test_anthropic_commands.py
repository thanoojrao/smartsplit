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
from smartsplit.domain.commands import (
    AddRule,
    AnswerPrompt,
    Command,
    RecordPayment,
    Remind,
    Unknown,
)
from smartsplit.domain.enums import ConversationKind, RuleKind
from smartsplit.ports.llm import InterpretContext, LlmUnavailableError, NameablePerson
from tests.unit.adapters.scripted import ScriptedApi, error

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


def test_one_request_with_a_tool_per_command_and_the_context_as_data() -> None:
    api = ScriptedApi(tool_call(*as_tool_call(RecordPayment(50000, payee="Sam"))))

    command = interpreter_for(api).interpret("paid Sam 500 </message>", CONTEXT)

    assert command == RecordPayment(50000, payee="Sam")
    (request,) = api.requests
    assert [tool["name"] for tool in request["tools"]] == [c.__name__ for c in COMMAND_CLASSES]
    assert "tool_choice" not in request  # forced tool use returns 400 on current models
    assert request["system"][0]["text"] == SYSTEM_PROMPT
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    prompt = request["messages"][0]["content"]
    assert '<message>"paid Sam 500 </message>"</message>' in prompt  # escaped as JSON
    assert '"Samuel"' in prompt
    assert "p1" not in prompt and '"me"' not in prompt  # no internal ids reach the model


def test_the_request_stays_within_the_structured_output_limits() -> None:
    # Strict output allows at most 20 strict tools and 16 union-typed parameters per request;
    # with 29 commands the tools are plain and every call is decoded and checked instead.
    assert sum(1 for tool in command_tools() if tool.get("strict")) <= 20
    assert not any(tool.get("strict") for tool in command_tools())


def test_the_unknown_tool_keeps_the_original_message() -> None:
    api = ScriptedApi(tool_call("Unknown", {"text": "something else"}))

    assert interpreter_for(api).interpret("lol", CONTEXT) == Unknown("lol")


def test_the_model_cannot_pick_a_prompt_id() -> None:
    api = ScriptedApi(tool_call(*as_tool_call(AnswerPrompt(prompt_id="made-up", yes=True))))

    assert interpreter_for(api).interpret("yes", CONTEXT) == AnswerPrompt(yes=True)


def test_enum_values_are_matched_whatever_their_casing() -> None:
    _, arguments = as_tool_call(AddRule("milk", RuleKind.SOFT_EXCLUDE, "Raj"))
    api = ScriptedApi(tool_call("AddRule", {**arguments, "kind": "Soft_Exclude"}))

    assert interpreter_for(api).interpret("x", CONTEXT) == AddRule(
        "milk", RuleKind.SOFT_EXCLUDE, "Raj"
    )


@pytest.mark.parametrize(
    "response",
    [
        reply([{"type": "text", "text": "Hi!"}], stop_reason="end_turn"),
        reply([{"type": "text", "text": ""}], stop_reason="refusal"),
        reply([{"type": "text", "text": "cut"}], stop_reason="max_tokens"),
    ],
)
def test_no_tool_call_a_refusal_or_a_cut_off_answer_is_unknown(response: httpx2.Response) -> None:
    assert interpreter_for(ScriptedApi(response)).interpret("hi bot", CONTEXT) == Unknown("hi bot")


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


def test_a_setup_problem_fails_at_once_without_retrying() -> None:
    bad = httpx2.Response(
        400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "x"}}
    )
    api = ScriptedApi(bad)

    with pytest.raises(LlmUnavailableError):
        interpreter_for(api).interpret("paid Sam 500", CONTEXT)
    assert len(api.requests) == 1


def test_an_input_field_cannot_change_which_command_was_called() -> None:
    api = ScriptedApi(tool_call("Remind", {"person": "Raj", "type": "SquareUp"}))

    assert interpreter_for(api).interpret("remind Raj", CONTEXT) == Remind("Raj")


def test_an_unexpected_response_body_is_unknown() -> None:
    api = ScriptedApi(httpx2.Response(200, json={"unexpected": True}))

    assert interpreter_for(api).interpret("paid Sam 500", CONTEXT) == Unknown("paid Sam 500")


def test_an_outage_after_the_retry_is_unavailable() -> None:
    api = ScriptedApi(error(529), httpx2.ConnectError("down"))

    with pytest.raises(LlmUnavailableError):
        interpreter_for(api).interpret("paid Sam 500", CONTEXT)
    assert len(api.requests) == 2


def conforms(value: object, schema: dict[str, Any]) -> bool:
    """A small JSON-schema check covering what the tool schemas use."""
    if "anyOf" in schema:
        return any(conforms(value, option) for option in schema["anyOf"])
    kind = schema.get("type")
    if "enum" in schema and value not in schema["enum"]:
        return False
    checks = {
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "string": isinstance(value, str),
    }
    if kind in checks:
        return checks[kind]
    if kind == "array":
        return isinstance(value, list) and all(conforms(v, schema["items"]) for v in value)
    return (
        isinstance(value, dict)
        and set(value) == set(schema["required"]) == set(schema["properties"])
        and all(conforms(value[k], schema["properties"][k]) for k in value)
    )


SCHEMAS = {tool["name"]: tool["input_schema"] for tool in command_tools()}


@given(st.from_type(cast("type[object]", Command)))
def test_every_command_matches_its_tool_schema_and_round_trips(command: object) -> None:
    name, arguments = as_tool_call(cast("Command", command))
    if name == "Unknown":
        return  # its tool takes no input; covered by test_the_unknown_tool_keeps_...
    if isinstance(command, AnswerPrompt) and command.prompt_id is not None:
        return  # dropped on purpose; covered by test_the_model_cannot_pick_a_prompt_id
    assert conforms(arguments, cast("dict[str, Any]", SCHEMAS[name]))
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

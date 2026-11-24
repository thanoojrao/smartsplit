"""The Anthropic agent and canonicalizer adapters, through the real SDK on a scripted
transport (SPEC 8.7, 12.5)."""

import anthropic
import httpx2
import pytest

from smartsplit.adapters.llm.agent import AnthropicAgent
from smartsplit.adapters.llm.canonicalizer import AnthropicCanonicalizer
from smartsplit.adapters.llm.receipts import anthropic_client
from smartsplit.ports.agent import AgentRequest, ModelStep, ModelUsage, ToolCall, ToolResult
from smartsplit.ports.llm import LlmUnavailableError
from smartsplit.services.tools.catalog import TOOL_SPECS
from tests.unit.adapters.scripted import ScriptedApi, error, message


def client_for(api: ScriptedApi) -> anthropic.Anthropic:
    return anthropic_client(
        "test-key", 30.0, anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(api))
    )


def agent_for(api: ScriptedApi) -> AnthropicAgent:
    return AnthropicAgent(client_for(api), model="claude-haiku-5-5", max_tokens=16000)


def tool_use_answer() -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_2",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": "Starting it."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "start_receipt",
                    "input": {"people": ["P2"]},
                },
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 50,
                "output_tokens": 20,
                "cache_read_input_tokens": 4000,
                "cache_creation_input_tokens": 0,
            },
        },
    )


REQUEST = AgentRequest("system prompt", TOOL_SPECS, "<state>…</state>", (), 12.0)


def test_a_step_with_tool_calls_keeps_its_blocks_for_replay() -> None:
    api = ScriptedApi(tool_use_answer())
    step = agent_for(api).step(REQUEST)
    assert step.tool_calls == (ToolCall("toolu_1", "start_receipt", {"people": ["P2"]}),)
    assert step.text == "Starting it."
    assert step.usage == ModelUsage(50, 4000, 0, 20)
    assert [b["type"] for b in step.replay] == ["thinking", "text", "tool_use"]


def test_the_request_has_the_cached_prefix_and_no_forced_tool_choice() -> None:
    api = ScriptedApi(message("Hi."))
    agent_for(api).step(REQUEST)
    sent = api.requests[0]
    assert sent["model"] == "claude-haiku-5-5"
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in sent["tools"]] == [s.name for s in TOOL_SPECS]
    assert sent["tool_choice"] == {"type": "auto"}
    assert sent["messages"] == [{"role": "user", "content": "<state>…</state>"}]


def test_the_final_step_keeps_the_tools_but_allows_no_call() -> None:
    api = ScriptedApi(message("Done."))
    step = agent_for(api).step(AgentRequest("s", TOOL_SPECS, "t", (), 5.0, final=True))
    assert api.requests[0]["tool_choice"] == {"type": "none"}
    assert len(api.requests[0]["tools"]) == len(TOOL_SPECS)
    assert step == ModelStep((), "Done.", ModelUsage(10, 0, 0, 10), step.replay)


def test_history_is_replayed_unchanged_with_the_tool_results() -> None:
    api = ScriptedApi(tool_use_answer(), message("All set."))
    agent = agent_for(api)
    first = agent.step(REQUEST)
    results = (
        ToolResult("toolu_1", True, {"draft": "D1"}, None, ("Toit, ₹2,047.00",)),
        ToolResult("toolu_2", False, {}, "There's no line 9.", ()),
    )
    agent.step(AgentRequest("s", TOOL_SPECS, "t", ((first, results),), 5.0))
    assistant, user = api.requests[1]["messages"][1:]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}
    assert user["content"][0]["tool_use_id"] == "toolu_1"
    assert user["content"][0]["is_error"] is False
    assert '"shown_to_the_chat": ["Toit, ₹2,047.00"]' in user["content"][0]["content"]
    assert user["content"][1]["is_error"] is True
    assert "There's no line 9." in user["content"][1]["content"]


def test_steps_without_replay_are_rebuilt_from_calls_and_text() -> None:
    api = ScriptedApi(message("ok"))
    scripted = ModelStep((ToolCall("c1", "get_balances", {}),), "Looking.")
    agent_for(api).step(AgentRequest("s", TOOL_SPECS, "t", ((scripted, ()),), 5.0))
    assert api.requests[0]["messages"][1]["content"] == [
        {"type": "text", "text": "Looking."},
        {"type": "tool_use", "id": "c1", "name": "get_balances", "input": {}},
    ]


def test_a_refusal_or_a_cut_off_answer_says_nothing() -> None:
    api = ScriptedApi(message("partial", stop_reason="max_tokens"))
    assert agent_for(api).step(REQUEST).text == ""


def test_errors_that_can_pass_are_retried_once_and_setup_errors_are_not() -> None:
    api = ScriptedApi(error(529), message("ok"))
    assert agent_for(api).step(REQUEST).text == "ok"
    with pytest.raises(LlmUnavailableError):
        agent_for(ScriptedApi(error(500), error(503))).step(REQUEST)
    failing = ScriptedApi(error(400))
    with pytest.raises(LlmUnavailableError):
        agent_for(failing).step(REQUEST)
    assert len(failing.requests) == 1


def canonicalizer_for(api: ScriptedApi) -> AnthropicCanonicalizer:
    return AnthropicCanonicalizer(
        client_for(api), model="claude-haiku-5-5", max_tokens=1000, timeout_seconds=9
    )


def test_canonicalize_answers_a_key_and_falls_back_to_the_name() -> None:
    api = ScriptedApi(message('{"item_key": "Milk"}'), message("not json"))
    canonicalizer = canonicalizer_for(api)
    assert canonicalizer.canonicalize("2% MLK GAL", ["milk", "bread"]) == "milk"
    assert canonicalizer.canonicalize("Oat  MLK", ["milk"]) == "oat mlk"
    assert '"milk", "bread"' in api.requests[0]["messages"][0]["content"]
    assert api.requests[0]["output_config"]["effort"] == "low"

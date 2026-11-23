"""A scripted stand-in for the Anthropic API, served through the real SDK's HTTP layer."""

import json
from typing import Any

import httpx2

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

"""One retry for errors that can pass, shared by the agent and canonicalize calls."""

from collections.abc import Callable

import anthropic
from anthropic.types import Message

from smartsplit.adapters.llm.usage import log_usage
from smartsplit.ports.llm import LlmUnavailableError

_RETRYABLE = frozenset({408, 409, 429})
_SERVER_ERRORS = 500


def call_once_more(purpose: str, request: Callable[[], Message]) -> Message:
    """One retry, but only for errors that can pass (network, 408/409/429, 5xx); a setup
    problem (any other 4xx) fails at once. Each answer's token usage is logged."""
    try:
        response = request()
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
        if not _retryable(error):
            raise LlmUnavailableError(type(error).__name__) from error
        try:
            response = request()
        except anthropic.APIError as retry_error:
            raise LlmUnavailableError(type(retry_error).__name__) from retry_error
    log_usage(purpose, response)
    return response


def _retryable(error: anthropic.APIError) -> bool:
    if isinstance(error, anthropic.APIStatusError):
        return error.status_code in _RETRYABLE or error.status_code >= _SERVER_ERRORS
    return True

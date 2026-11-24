"""One retry for errors that can pass, shared by the agent and canonicalize calls."""

from collections.abc import Callable
from time import monotonic

import anthropic
from anthropic.types import Message

from smartsplit.adapters.llm.usage import log_usage
from smartsplit.ports.llm import CountCall, LlmUnavailableError

_RETRYABLE = frozenset({408, 409, 429})
_SERVER_ERRORS = 500
MIN_RETRY_SECONDS = 1.0
"""A retry with less time than this left would only time out."""


def call_once_more(
    purpose: str,
    request: Callable[[float], Message],
    *,
    timeout_seconds: float,
    count_call: CountCall,
) -> Message:
    """One retry, but only for errors that can pass (network, a timeout, 408/409/429, 5xx);
    a setup problem (any other 4xx) fails at once. `timeout_seconds` covers both attempts:
    the retry gets what is left, and isn't made with less than a second left. `request`
    takes the timeout for its attempt. Every attempt is counted and its usage logged."""
    time_left = countdown(timeout_seconds)
    try:
        count_call()
        response = request(timeout_seconds)
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
        left = time_left()
        if not _retryable(error) or left < MIN_RETRY_SECONDS:
            raise LlmUnavailableError(type(error).__name__) from error
        try:
            count_call()
            response = request(left)
        except anthropic.APIError as retry_error:
            raise LlmUnavailableError(type(retry_error).__name__) from retry_error
    log_usage(purpose, response)
    return response


def countdown(timeout_seconds: float) -> Callable[[], float]:
    """Seconds left of `timeout_seconds` counted from now, each time it is called."""
    started = monotonic()
    return lambda: timeout_seconds - (monotonic() - started)


def _retryable(error: anthropic.APIError) -> bool:
    if isinstance(error, anthropic.APIStatusError):
        return error.status_code in _RETRYABLE or error.status_code >= _SERVER_ERRORS
    return True

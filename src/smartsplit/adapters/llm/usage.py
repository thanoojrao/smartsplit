"""One log line per model call with its token usage, so cost and caching can be checked.

The line holds only counts and the call's purpose: no prompt text, names or numbers
(SPEC 12.4). Logged at INFO on `smartsplit.llm`.
"""

import logging

from anthropic.types import Message

log = logging.getLogger("smartsplit.llm")


def log_usage(purpose: str, response: Message) -> None:
    """`purpose` is "agent", "canonicalize" or "receipt". An answer without a usage
    block (malformed) is not logged: logging never breaks a call."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    log.info(
        "model call purpose=%s model=%s input_tokens=%d cache_read_tokens=%d "
        "cache_write_tokens=%d output_tokens=%d",
        purpose,
        response.model,
        usage.input_tokens,
        usage.cache_read_input_tokens or 0,
        usage.cache_creation_input_tokens or 0,
        usage.output_tokens,
    )

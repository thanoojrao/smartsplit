"""What the live scenarios record for the end-of-run summary: messages sent to the real model
and replies that asked something (SPEC 12.5: questions asked is a quality measure)."""

from dataclasses import dataclass, field


@dataclass
class ScenarioLog:
    name: str
    messages: int = 0
    """Messages that reached the real model (setup with the scripted agent isn't counted)."""
    asked: int = 0
    """Replies whose own words (before any code-rendered block) end a sentence with "?"."""
    lines: list[str] = field(default_factory=list)
    """The conversation, printed in the summary when the scenario fails."""


SCENARIOS: dict[str, ScenarioLog] = {}

"""Every tool, in a fixed order: the tool definitions are part of the cached prompt prefix
(SPEC 12.5), so they never change between turns."""

from typing import Any

from smartsplit.ports.agent import ToolSpec
from smartsplit.services.tools.actions import ACTION_TOOLS
from smartsplit.services.tools.drafts import DRAFT_TOOLS
from smartsplit.services.tools.people import PEOPLE_TOOLS
from smartsplit.services.tools.reading import READ_TOOLS
from smartsplit.services.tools.registry import Tool

ALL_TOOLS: tuple[Tool[Any], ...] = (*READ_TOOLS, *DRAFT_TOOLS, *PEOPLE_TOOLS, *ACTION_TOOLS)

TOOL_SPECS: tuple[ToolSpec, ...] = tuple(tool.spec() for tool in ALL_TOOLS)

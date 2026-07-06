"""Tool management types.

[INPUT]
- langchain_core.tools::BaseTool (POS: LangChain tool base)
- .tool_layers::ToolLayer (POS: layer enum for cache ordering)

[OUTPUT]
- ToolSource: enum of tool origins (META, USER, MIDDLEWARE)
- ToolEntry: dataclass wrapping a tool with source metadata
- ToolSnapshot: lightweight tool info for runtime availability view; ``builtin_tool_id`` maps GUI togglable products when applicable.

[POS]
Core types for the tool management subsystem.
ToolSource tracks provenance; ToolEntry bundles a tool with its source and layer.
ToolSnapshot provides a serializable view of resolved tools for API exposure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.tool_management.tool_layers import ToolLayer


class ToolSource(Enum):
    """Where a tool was registered from.

    Priority order (higher wins on name collision):
    META > USER > MIDDLEWARE
    """

    META = "meta"
    USER = "user"
    MIDDLEWARE = "middleware"


class ToolBindMode(str, Enum):
    """How a tool participates in Turn1 bind_tools and discover_capability.

    TURN1: bound on first model turn (default).
    DISCOVERABLE: excluded from Turn1; indexed by discover_capability; AutoMount on hit.
    RUNTIME_ONLY: excluded from Turn1 and discover; executable when middleware injects tool_calls.
    """

    TURN1 = "turn1"
    DISCOVERABLE = "discoverable"
    RUNTIME_ONLY = "runtime_only"


_SOURCE_PRIORITY: dict[ToolSource, int] = {
    ToolSource.META: 0,
    ToolSource.USER: 1,
    ToolSource.MIDDLEWARE: 2,
}


def source_priority(source: ToolSource) -> int:
    """Lower value = higher priority."""
    return _SOURCE_PRIORITY.get(source, 99)


@dataclass(slots=True)
class ToolEntry:
    """A tool bundled with provenance metadata."""

    tool: BaseTool
    source: ToolSource
    layer: ToolLayer | None = field(default=None)
    provider: str | None = field(default=None)
    allowed_domains: list[str] | None = field(default=None)
    bind_mode: ToolBindMode = field(default=ToolBindMode.TURN1)


@dataclass(slots=True, frozen=True)
class ToolSnapshot:
    """Lightweight, serializable tool info for the runtime availability view."""

    name: str
    summary: str
    description: str
    source: str
    provider: str | None
    layer: str
    parameters_schema: dict[str, object] | None
    bind_mode: str = field(default=ToolBindMode.TURN1.value)
    builtin_tool_id: str | None = field(default=None)

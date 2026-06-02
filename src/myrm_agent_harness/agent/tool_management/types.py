"""Tool management types.

[INPUT]
- langchain_core.tools::BaseTool (POS: LangChain tool base)
- .tool_layers::ToolLayer (POS: layer enum for cache ordering)

[OUTPUT]
- ToolSource: enum of tool origins (META, USER, MIDDLEWARE)
- ToolEntry: dataclass wrapping a tool with source metadata
- ToolSnapshot: lightweight tool info for runtime availability view

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
    deferred: bool = field(default=False)


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
    deferred: bool = field(default=False)

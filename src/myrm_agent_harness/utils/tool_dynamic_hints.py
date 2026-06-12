"""Cross-tool dependency hint injection for LangChain tools.

[INPUT]
- langchain_core.tools::BaseTool (POS: LangChain tool instance to decorate)

[OUTPUT]
- with_dynamic_hints: inject and weave cross-tool dependency hints into tool descriptions

[POS]
Shared by agent tool factories and toolkit tool factories without toolkits→agent imports.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from collections.abc import Set


def with_dynamic_hints(tool: BaseTool, hints: dict[str, str]) -> BaseTool:
    """Safely inject cross-tool dependency hints into a tool's description."""
    base_desc = tool.description or ""

    initial_desc = base_desc
    if hints:
        initial_desc += " " + " ".join(hints.values())

    if hasattr(tool, "model_copy"):
        decorated_tool = tool.model_copy(update={"description": initial_desc})
    else:
        decorated_tool = copy.copy(tool)
        decorated_tool.description = initial_desc

    def _dynamic_modifier(available_names: Set[str]) -> BaseTool:
        new_desc = base_desc
        active_hints = [hint for t_name, hint in hints.items() if t_name in available_names]
        if active_hints:
            new_desc += " " + " ".join(active_hints)

        if hasattr(decorated_tool, "model_copy"):
            return decorated_tool.model_copy(update={"description": new_desc})

        new_tool = copy.copy(decorated_tool)
        new_tool.description = new_desc
        return new_tool

    try:
        decorated_tool.dynamic_schema_modifier = _dynamic_modifier
    except (ValueError, TypeError, AttributeError):
        object.__setattr__(decorated_tool, "dynamic_schema_modifier", _dynamic_modifier)

    return decorated_tool


__all__ = ["with_dynamic_hints"]

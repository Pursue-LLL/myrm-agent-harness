"""Tool management utilities.

[OUTPUT]
- with_dynamic_hints: Decorator to safely inject cross-tool dependency hints.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from collections.abc import Set


def with_dynamic_hints(tool: BaseTool, hints: dict[str, str]) -> BaseTool:
    """Safely inject cross-tool dependency hints into a tool's description.

    This function avoids the fragile "string replace" anti-pattern. It sets the
    initial tool description to include all hints, but binds a
    `dynamic_schema_modifier` hook to the tool. During agent graph build
    (ToolRegistry.resolve -> _weave_dynamic_schemas), this hook reconstructs
    a clean description including only hints for tools that actually exist in the
    current sandbox environment.

    Args:
        tool: The LangChain tool instance to decorate.
        hints: A dictionary mapping target tool names to their hint sentences.
               e.g. {"web_search_tool": "Prefer web_search_tool for news."}

    Returns:
        The decorated BaseTool (mutated in-place with the hook, but safely
        clones itself when the hook executes).
    """
    base_desc = tool.description or ""

    # Initialize description with all hints
    initial_desc = base_desc
    if hints:
        initial_desc += " " + " ".join(hints.values())

    # Copy upfront to avoid singleton mutation across test runs or instances
    if hasattr(tool, "model_copy"):
        decorated_tool = tool.model_copy(update={"description": initial_desc})
    else:
        decorated_tool = copy.copy(tool)
        decorated_tool.description = initial_desc

    def _dynamic_modifier(available_names: Set[str]) -> BaseTool:
        # Rebuild clean description
        new_desc = base_desc
        active_hints = [hint for t_name, hint in hints.items() if t_name in available_names]
        if active_hints:
            new_desc += " " + " ".join(active_hints)

        # Write-on-copy (Copy-on-Weave) to prevent global singleton pollution
        if hasattr(decorated_tool, "model_copy"):
            return decorated_tool.model_copy(update={"description": new_desc})

        # Fallback for generic objects
        new_tool = copy.copy(decorated_tool)
        new_tool.description = new_desc
        return new_tool

    # Bind the hook duck-type
    # Using object.__setattr__ to bypass strict pydantic model constraints if needed
    try:
        decorated_tool.dynamic_schema_modifier = _dynamic_modifier
    except (ValueError, TypeError, AttributeError):
        object.__setattr__(decorated_tool, "dynamic_schema_modifier", _dynamic_modifier)

    return decorated_tool

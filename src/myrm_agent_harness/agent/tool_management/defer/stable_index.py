"""StableDeferredIndex — sorted deferred tool names for frozen system prompt.

[POS]
Builds ``<available-deferred-tools>`` stable system prompt section (sorted names only).
"""

from __future__ import annotations

from collections.abc import Sequence

DEFERRED_TOOLS_MARKER = "<available-deferred-tools>"


def build_deferred_tools_prompt_section(deferred_names: Sequence[str]) -> str:
    """Build ``<available-deferred-tools>`` block for system prompt injection."""
    if not deferred_names:
        return ""
    names = "\n".join(sorted(deferred_names))
    return (
        f"{DEFERRED_TOOLS_MARKER}\n"
        "Native tools listed below are not in Turn1 bind_tools. "
        "Call invoke_deferred_tool(name, arguments) to run them, "
        "or discover_capability_tool when bound to search by query.\n"
        f"{names}\n"
        f"</available-deferred-tools>"
    )

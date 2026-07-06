"""Runtime hook names — middleware-injected pseudo tool_calls.

[OUTPUT]
- COMPLETION_CHECK_TOOL_NAME: CompletionGuard hook name constant
- RUNTIME_HOOK_NAMES: SSOT frozenset of hook tool names
- is_runtime_hook(): membership check

[POS]
Runtime hooks are BaseTool instances registered with ``ToolBindMode.RUNTIME_ONLY``.
They are excluded from ``_TOOL_LAYERS``, action-tool counts, and discover_capability index.
"""

from __future__ import annotations

COMPLETION_CHECK_TOOL_NAME = "_completion_check"

RUNTIME_HOOK_NAMES: frozenset[str] = frozenset({COMPLETION_CHECK_TOOL_NAME})


def is_runtime_hook(tool_name: str) -> bool:
    """Return True when *tool_name* is a middleware runtime hook."""
    return tool_name in RUNTIME_HOOK_NAMES

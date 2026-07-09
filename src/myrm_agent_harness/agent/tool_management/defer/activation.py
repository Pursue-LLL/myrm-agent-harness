"""Format discover_capability deferred hits for invoke_deferred_tool.

[POS]
Formats ``DeferredToolHit`` lines for discover_capability ToolMessage output.
"""

from __future__ import annotations

import json


def format_deferred_tool_hit(name: str, schema: dict[str, object]) -> str:
    """Format a single ``DeferredToolHit`` line for discover_capability output."""
    schema_hint = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    escaped = schema_hint.replace('"', "&quot;")
    return f'<DeferredToolHit name="{name}" schema_hint="{escaped}"/>'

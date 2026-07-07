"""Parse discover_capability deferred hits for invoke_deferred_tool."""

from __future__ import annotations

import json
import re

_DEFERRED_HIT_PATTERN = re.compile(
    r'<DeferredToolHit\s+name="([^"]+)"(?:\s+schema_hint="([^"]*)")?\s*/>',
)
_DISCOVER_TOOL_MESSAGE_NAMES = frozenset(
    {"discover_capability", "discover_capability_tool"}
)


def is_discover_capability_tool_message(name: str | None) -> bool:
    """Match ToolMessage.name for the discovery meta-tool."""
    return bool(name) and name in _DISCOVER_TOOL_MESSAGE_NAMES


def parse_deferred_tool_hits(content: str) -> set[str]:
    """Extract deferred tool names from discover_capability ToolMessage content."""
    return {match.group(1) for match in _DEFERRED_HIT_PATTERN.finditer(content)}


def format_deferred_tool_hit(name: str, schema: dict[str, object]) -> str:
    """Format a single ``DeferredToolHit`` line for discover_capability output."""
    schema_hint = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    escaped = schema_hint.replace('"', "&quot;")
    return f'<DeferredToolHit name="{name}" schema_hint="{escaped}"/>'

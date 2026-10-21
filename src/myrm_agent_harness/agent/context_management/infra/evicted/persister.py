"""Large tool output persister — delegates to UECD evicted directory.

[INPUT]
- evicted.content::persist_evicted_content, sanitize_evicted_source

[OUTPUT]
- persist_large_tool_output

[POS]
FilterProcessor backup persist layer (replaces legacy .myrm/artifacts path).
"""

from __future__ import annotations

import logging

from myrm_agent_harness.agent.context_management.infra.evicted.content import (
    persist_evicted_content,
    sanitize_evicted_source,
)

logger = logging.getLogger(__name__)


async def persist_large_tool_output(content: str, tool_name: str | None) -> str | None:
    """Persist large tool output to the session evicted directory."""
    source = sanitize_evicted_source(tool_name or "filter")
    if tool_name and "mcp" in tool_name.lower():
        source = "mcp"
    result = await persist_evicted_content(content, source, ext="txt")
    if result.rel_path:
        logger.info("[ToolOutputPersister] Saved via UECD to %s", result.rel_path)
        return result.rel_path
    return None

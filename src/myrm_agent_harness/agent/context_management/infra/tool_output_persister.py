"""Large tool output persister.

Saves oversized tool results to disk before FilterProcessor truncates them,
so the agent can later read the full content via file_read_tool.

Architecture:
  bash tool → _output_eviction.py (first line, saves to sandbox)
  all tools → FilterProcessor → tool_output_persister (second line, saves to workspace)

The two layers are independent: bash output is already evicted before reaching
FilterProcessor, so only non-bash tools (MCP, future tools) trigger this module.

[INPUT]
- (none)

[OUTPUT]
- persist_large_tool_output: Persist large tool output to a file.

[POS]
Large tool output persister.
"""

import logging
import re
import time
from pathlib import Path

from myrm_agent_harness.infra.atomic_write import async_atomic_write

logger = logging.getLogger(__name__)

_ARTIFACT_DIR = ".myrm/artifacts/tool_outputs"
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_NAME_LEN = 40


def _sanitize_name(name: str) -> str:
    """Normalize a tool name into a safe filesystem component."""
    sanitized = _SAFE_NAME_RE.sub("_", name)
    if len(sanitized) > _MAX_NAME_LEN:
        sanitized = sanitized[:_MAX_NAME_LEN]
    return sanitized or "unknown"


async def persist_large_tool_output(content: str, tool_name: str | None) -> str | None:
    """Persist large tool output to a file.

    Args:
        content: The full tool output text.
        tool_name: Name of the tool that produced the output.

    Returns:
        Relative path (from workspace root) on success, or None on failure.
    """
    from myrm_agent_harness.agent.middlewares._session_context import get_workspace_root

    workspace_root = get_workspace_root()
    if not workspace_root:
        logger.warning("[ToolOutputPersister] No workspace root, skipping persist")
        return None

    safe_name = _sanitize_name(tool_name or "tool")
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    relative_path = f"{_ARTIFACT_DIR}/{safe_name}_{timestamp}.txt"
    absolute_path = Path(workspace_root) / relative_path

    try:
        await async_atomic_write(absolute_path, content)
        logger.info(f"[ToolOutputPersister] Saved {len(content)} chars to {relative_path}")
        return relative_path
    except Exception as e:
        logger.warning(f"[ToolOutputPersister] Failed to persist: {e}")
        return None

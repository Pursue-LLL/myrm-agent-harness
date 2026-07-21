"""Smart parallel tool batch router based on path scope and AST."""

import os
from pathlib import Path
from typing import Any

from myrm_agent_harness.agent.security.tool_registry import SafetyMetadata, resolve_safety_metadata
from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

_PATH_SCOPED_TOOLS = {
    "file_write_tool",
    "file_patch_tool",
    "file_read_tool",
    "file_search_tool",
    "file_glob_tool",
    "grep_search_tool",
}


def _extract_host_serial_lane(tool_name: str, metadata: SafetyMetadata) -> str | None:
    """Return MCP server lane when a call is unsafe only due to host-serial override.

    Host-serial demotion in MCP marks read-only tools as ``is_concurrent_safe=False``
    even though they are not destructive. We can still parallelize such calls across
    different MCP servers, but never twice on the same server in one batch.
    """
    if metadata.is_concurrent_safe:
        return None
    if not metadata.is_read_only:
        return None
    if metadata.is_destructive or metadata.is_open_world:
        return None
    parsed = parse_mcp_tool_name(tool_name)
    if parsed is None:
        return None
    server_name, _tool_name = parsed
    return server_name or None


def _paths_overlap(left: Path, right: Path) -> bool:
    """Return True when two paths may refer to the same subtree."""
    left_parts = left.parts
    right_parts = right.parts
    if not left_parts or not right_parts:
        return bool(left_parts) == bool(right_parts) and bool(left_parts)
    common_len = min(len(left_parts), len(right_parts))
    return left_parts[:common_len] == right_parts[:common_len]


def _extract_parallel_scope_path(tool_name: str, function_args: dict[str, Any]) -> Path | None:
    """Return the normalized file target for path-scoped tools."""
    if tool_name not in _PATH_SCOPED_TOOLS:
        return None

    raw_path = function_args.get("path") or function_args.get("file_path") or function_args.get("file")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None

    expanded = Path(raw_path).expanduser()
    if expanded.is_absolute():
        return Path(os.path.abspath(str(expanded)))

    return Path(os.path.abspath(str(Path.cwd() / expanded)))


def should_parallelize_tool_batch(tool_calls: list[dict[str, Any]]) -> bool:
    """Return True when a tool-call batch is safe to run concurrently."""
    if len(tool_calls) <= 1:
        return False

    reserved_paths: list[Path] = []
    reserved_host_serial_lanes: set[str] = set()

    for tool_call in tool_calls:
        tool_name = str(tool_call.get("name", ""))
        metadata = resolve_safety_metadata(tool_name)

        if metadata.is_concurrent_safe and tool_name not in _PATH_SCOPED_TOOLS:
            continue

        if tool_name not in _PATH_SCOPED_TOOLS and not metadata.is_concurrent_safe:
            host_serial_lane = _extract_host_serial_lane(tool_name, metadata)
            if host_serial_lane is None:
                return False
            if host_serial_lane in reserved_host_serial_lanes:
                return False
            reserved_host_serial_lanes.add(host_serial_lane)
            continue

        args = tool_call.get("args", {})
        if not isinstance(args, dict):
            return False

        scoped_path = _extract_parallel_scope_path(tool_name, args)
        if scoped_path is None:
            if not metadata.is_concurrent_safe:
                return False
            continue

        if any(_paths_overlap(scoped_path, existing) for existing in reserved_paths):
            return False

        # ALL path-scoped operations reserve the path to prevent dirty reads
        reserved_paths.append(scoped_path)

    return True

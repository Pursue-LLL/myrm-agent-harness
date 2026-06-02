"""Smart parallel tool batch router based on path scope and AST."""

import os
from pathlib import Path
from typing import Any

from myrm_agent_harness.agent.security.tool_registry import resolve_safety_metadata

_PATH_SCOPED_TOOLS = {
    "file_write_tool",
    "file_patch_tool",
    "file_read_tool",
    "file_search_tool",
    "file_glob_tool",
    "grep_search_tool"
}

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

    for tool_call in tool_calls:
        tool_name = str(tool_call.get("name", ""))
        metadata = resolve_safety_metadata(tool_name)

        if metadata.is_concurrent_safe and tool_name not in _PATH_SCOPED_TOOLS:
            continue

        if tool_name not in _PATH_SCOPED_TOOLS and not metadata.is_concurrent_safe:
            return False

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

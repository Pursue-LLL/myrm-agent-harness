"""Smart tool execution routing based on path scope and safety metadata.

[INPUT]
- agent.security.tool_registry::resolve_safety_metadata (POS: tool safety metadata resolver)
- toolkits.mcp.config::parse_mcp_tool_name (POS: parse ``mcp__server__tool`` names)
- file_ops.path_utils::resolve_file_id_path (POS: resolve ``@file_xxx`` aliases)

[OUTPUT]
- build_tool_execution_stages: ordered stage plan for mixed concurrent/serial tool batches
- should_parallelize_tool_batch: bool helper for full-batch one-stage parallelism

[POS]
Path-aware concurrency planner. It enforces read/write conflict isolation and
host-serial MCP lane constraints while preserving safe parallel execution.
"""

import os
from pathlib import Path
from typing import Any, Literal

from myrm_agent_harness.agent.security.tool_registry import SafetyMetadata, resolve_safety_metadata
from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

_PATH_SCOPED_TOOLS = frozenset(
    {
        "file_write_tool",
        "file_edit_tool",
        "file_read_tool",
        "grep_tool",
        "glob_tool",
    }
)

_TOOL_ALIASES = {
    # Legacy aliases kept for compatibility with historical transcripts.
    "file_patch_tool": "file_edit_tool",
    "file_replace_tool": "file_edit_tool",
    "file_search_tool": "file_read_tool",
    "file_glob_tool": "glob_tool",
    "grep_search_tool": "grep_tool",
}

_GLOB_META_CHARS = frozenset({"*", "?", "[", "]", "{", "}"})


_StageVerdict = Literal["fit", "conflict", "singleton"]


def _canonicalize_tool_name(tool_name: str) -> str:
    """Normalize historical aliases to canonical tool names."""
    return _TOOL_ALIASES.get(tool_name, tool_name)


def _resolve_parallel_scope_path(raw_path: str) -> str:
    """Resolve token-saving file IDs before path conflict planning."""
    from myrm_agent_harness.agent.meta_tools.file_ops.utils.path_utils import resolve_file_id_path

    return resolve_file_id_path(raw_path)


def _canonicalize_scope_path(path: Path) -> Path:
    """Canonicalize to stable filesystem identity (realpath + normcase)."""
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = Path(os.path.abspath(str(path)))
    return Path(os.path.normcase(str(resolved)))


def _normalize_scope_path(raw_path: str) -> Path | None:
    if not raw_path.strip():
        return None

    resolved_raw_path = _resolve_parallel_scope_path(raw_path)
    expanded = Path(resolved_raw_path).expanduser()
    absolute = expanded if expanded.is_absolute() else Path.cwd() / expanded
    return _canonicalize_scope_path(absolute)


def _normalize_scope_paths(raw_paths: list[str]) -> tuple[Path, ...]:
    normalized: list[Path] = []
    seen: set[str] = set()
    for raw in raw_paths:
        scope = _normalize_scope_path(raw)
        if scope is None:
            continue
        key = str(scope)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(scope)
    return tuple(normalized)


def _extract_glob_scope_path(pattern: str) -> Path | None:
    """Extract deterministic scope root from a glob pattern."""
    expanded = Path(pattern).expanduser()
    literal_parts: list[str] = []
    for part in expanded.parts:
        if any(ch in part for ch in _GLOB_META_CHARS):
            break
        literal_parts.append(part)

    if not literal_parts:
        return _canonicalize_scope_path(Path.cwd())

    if literal_parts[0] == os.sep:
        literal_path = Path(os.sep, *literal_parts[1:])
    else:
        literal_path = Path(*literal_parts)
        if not literal_path.is_absolute():
            literal_path = Path.cwd() / literal_path
    return _canonicalize_scope_path(literal_path)


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


def _classify_tool_call_for_stage(
    tool_call: dict[str, Any],
    reserved_read_paths: list[Path],
    reserved_write_paths: list[Path],
    reserved_host_serial_lanes: set[str],
) -> tuple[_StageVerdict, tuple[Path, ...], str | None, bool]:
    """Classify whether a tool call can join the current parallel stage.

    Returns:
    - ``fit``: can run in this stage and contributes optional reservations.
    - ``conflict``: can run concurrently in principle, but conflicts with reservations
      already taken by this stage (start a new stage).
    - ``singleton``: cannot safely run concurrently with any other call.
    """
    raw_tool_name = str(tool_call.get("name", ""))
    tool_name = _canonicalize_tool_name(raw_tool_name)
    metadata = resolve_safety_metadata(tool_name)

    if metadata.is_concurrent_safe and tool_name not in _PATH_SCOPED_TOOLS:
        return "fit", tuple(), None, False

    if tool_name not in _PATH_SCOPED_TOOLS and not metadata.is_concurrent_safe:
        host_serial_lane = _extract_host_serial_lane(tool_name, metadata)
        if host_serial_lane is None:
            return "singleton", tuple(), None, False
        if host_serial_lane in reserved_host_serial_lanes:
            return "conflict", tuple(), None, False
        return "fit", tuple(), host_serial_lane, False

    args = tool_call.get("args", {})
    if not isinstance(args, dict):
        return "singleton", tuple(), None, False

    scoped_paths = _extract_parallel_scope_paths(tool_name, args)
    if not scoped_paths:
        if not metadata.is_concurrent_safe:
            return "singleton", tuple(), None, False
        return "fit", tuple(), None, False

    if metadata.is_read_only:
        if _has_path_conflict(scoped_paths, reserved_write_paths):
            return "conflict", tuple(), None, False
        return "fit", scoped_paths, None, True

    if _has_path_conflict(scoped_paths, reserved_write_paths):
        return "conflict", tuple(), None, False
    if _has_path_conflict(scoped_paths, reserved_read_paths):
        return "conflict", tuple(), None, False
    return "fit", scoped_paths, None, False


def _has_path_conflict(candidates: tuple[Path, ...], reserved: list[Path]) -> bool:
    return any(_paths_overlap(candidate, existing) for candidate in candidates for existing in reserved)


def _paths_overlap(left: Path, right: Path) -> bool:
    """Return True when two paths may refer to the same subtree."""
    left_parts = left.parts
    right_parts = right.parts
    if not left_parts or not right_parts:
        return bool(left_parts) == bool(right_parts) and bool(left_parts)
    common_len = min(len(left_parts), len(right_parts))
    return left_parts[:common_len] == right_parts[:common_len]


def _extract_parallel_scope_paths(tool_name: str, function_args: dict[str, Any]) -> tuple[Path, ...]:
    """Return normalized path reservations for path-scoped tools."""
    if tool_name not in _PATH_SCOPED_TOOLS:
        return tuple()

    if tool_name == "file_read_tool":
        raw_paths = function_args.get("paths")
        if isinstance(raw_paths, list):
            paths = _normalize_scope_paths([p for p in raw_paths if isinstance(p, str) and p.strip()])
            if paths:
                return paths

    if tool_name == "glob_tool":
        raw_pattern = function_args.get("pattern")
        if isinstance(raw_pattern, str) and raw_pattern.strip():
            scope = _extract_glob_scope_path(raw_pattern)
            return (scope,) if scope is not None else tuple()

    raw_path = function_args.get("path") or function_args.get("file_path") or function_args.get("file")
    if not isinstance(raw_path, str):
        return tuple()

    scope = _normalize_scope_path(raw_path)
    return (scope,) if scope is not None else tuple()


def build_tool_execution_stages(tool_calls: list[dict[str, Any]]) -> list[list[int]]:
    """Plan execution stages for a tool-call batch.

    The planner preserves call order and groups only calls that can safely run in
    parallel in the same stage. Calls that are unsafe for any concurrency become
    singleton stages. Conflicting calls open a new stage.
    """
    if not tool_calls:
        return []

    stages: list[list[int]] = []
    current_stage: list[int] = []
    reserved_read_paths: list[Path] = []
    reserved_write_paths: list[Path] = []
    reserved_host_serial_lanes: set[str] = set()

    def _flush_stage() -> None:
        nonlocal current_stage, reserved_read_paths, reserved_write_paths, reserved_host_serial_lanes
        if current_stage:
            stages.append(current_stage)
        current_stage = []
        reserved_read_paths = []
        reserved_write_paths = []
        reserved_host_serial_lanes = set()

    def _append_with_reservations(
        idx: int,
        path_reservations: tuple[Path, ...],
        lane_reservation: str | None,
        path_read_only: bool,
    ) -> None:
        current_stage.append(idx)
        for path_reservation in path_reservations:
            if path_read_only:
                reserved_read_paths.append(path_reservation)
            else:
                reserved_write_paths.append(path_reservation)
        if lane_reservation is not None:
            reserved_host_serial_lanes.add(lane_reservation)

    for idx, tool_call in enumerate(tool_calls):
        verdict, path_reservation, lane_reservation, path_read_only = _classify_tool_call_for_stage(
            tool_call,
            reserved_read_paths,
            reserved_write_paths,
            reserved_host_serial_lanes,
        )

        if verdict == "fit":
            _append_with_reservations(idx, path_reservation, lane_reservation, path_read_only)
            continue

        if verdict == "conflict":
            _flush_stage()
            retry_verdict, retry_path_reservation, retry_lane_reservation, retry_path_read_only = (
                _classify_tool_call_for_stage(
                    tool_call,
                    reserved_read_paths,
                    reserved_write_paths,
                    reserved_host_serial_lanes,
                )
            )
            if retry_verdict == "fit":
                _append_with_reservations(
                    idx,
                    retry_path_reservation,
                    retry_lane_reservation,
                    retry_path_read_only,
                )
            else:
                # Defensive fallback: impossible to co-locate with anything.
                stages.append([idx])
            continue

        # singleton: isolate the call in its own stage.
        _flush_stage()
        stages.append([idx])

    _flush_stage()
    return stages


def should_parallelize_tool_batch(tool_calls: list[dict[str, Any]]) -> bool:
    """Return True when the full batch can run in one concurrent stage."""
    if len(tool_calls) <= 1:
        return False
    stages = build_tool_execution_stages(tool_calls)
    return len(stages) == 1 and len(stages[0]) > 1

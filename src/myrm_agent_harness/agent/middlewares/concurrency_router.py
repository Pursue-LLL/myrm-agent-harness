"""Smart tool execution routing based on path scope and safety metadata."""

import os
from pathlib import Path
from typing import Any, Literal

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


_StageVerdict = Literal["fit", "conflict", "singleton"]


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
    reserved_paths: list[Path],
    reserved_host_serial_lanes: set[str],
) -> tuple[_StageVerdict, Path | None, str | None]:
    """Classify whether a tool call can join the current parallel stage.

    Returns:
    - ``fit``: can run in this stage and contributes optional reservations.
    - ``conflict``: can run concurrently in principle, but conflicts with reservations
      already taken by this stage (start a new stage).
    - ``singleton``: cannot safely run concurrently with any other call.
    """
    tool_name = str(tool_call.get("name", ""))
    metadata = resolve_safety_metadata(tool_name)

    if metadata.is_concurrent_safe and tool_name not in _PATH_SCOPED_TOOLS:
        return "fit", None, None

    if tool_name not in _PATH_SCOPED_TOOLS and not metadata.is_concurrent_safe:
        host_serial_lane = _extract_host_serial_lane(tool_name, metadata)
        if host_serial_lane is None:
            return "singleton", None, None
        if host_serial_lane in reserved_host_serial_lanes:
            return "conflict", None, None
        return "fit", None, host_serial_lane

    args = tool_call.get("args", {})
    if not isinstance(args, dict):
        return "singleton", None, None

    scoped_path = _extract_parallel_scope_path(tool_name, args)
    if scoped_path is None:
        if not metadata.is_concurrent_safe:
            return "singleton", None, None
        return "fit", None, None

    if any(_paths_overlap(scoped_path, existing) for existing in reserved_paths):
        return "conflict", None, None

    # ALL path-scoped operations reserve the path to prevent dirty reads.
    return "fit", scoped_path, None


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
    reserved_paths: list[Path] = []
    reserved_host_serial_lanes: set[str] = set()

    def _flush_stage() -> None:
        nonlocal current_stage, reserved_paths, reserved_host_serial_lanes
        if current_stage:
            stages.append(current_stage)
        current_stage = []
        reserved_paths = []
        reserved_host_serial_lanes = set()

    def _append_with_reservations(idx: int, path_reservation: Path | None, lane_reservation: str | None) -> None:
        current_stage.append(idx)
        if path_reservation is not None:
            reserved_paths.append(path_reservation)
        if lane_reservation is not None:
            reserved_host_serial_lanes.add(lane_reservation)

    for idx, tool_call in enumerate(tool_calls):
        verdict, path_reservation, lane_reservation = _classify_tool_call_for_stage(
            tool_call,
            reserved_paths,
            reserved_host_serial_lanes,
        )

        if verdict == "fit":
            _append_with_reservations(idx, path_reservation, lane_reservation)
            continue

        if verdict == "conflict":
            _flush_stage()
            retry_verdict, retry_path_reservation, retry_lane_reservation = _classify_tool_call_for_stage(
                tool_call,
                reserved_paths,
                reserved_host_serial_lanes,
            )
            if retry_verdict == "fit":
                _append_with_reservations(idx, retry_path_reservation, retry_lane_reservation)
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

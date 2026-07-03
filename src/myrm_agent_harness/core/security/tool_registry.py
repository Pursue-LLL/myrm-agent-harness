"""Tool Registry — tool metadata and permission mapping.

Single source of truth for tool information:
1. Tool name → permission type mapping (for security evaluation)
2. Tool name → canonical parameters mapping (for stable hashing)
3. Tool name → safety metadata mapping (for concurrency scheduling & sub-agent filtering)

LangChain tools have concrete names (e.g. ``bash_code_execute_tool``),
while the Permission Engine operates on abstract permission types
(e.g. ``code_interpreter``, ``shell_exec``). This module bridges the two namespaces.

HOW TO ADD NEW ACTION CLASSIFICATION:

1. For browser_interact actions:
   Add to _INTERACT_ACTION_MAP: {"new_action": "browser_new_permission"}
   Example: {"scroll": "browser_scroll"} for independent scroll control

2. For browser_manage actions:
   Add to _MANAGE_ACTION_MAP: {"new_action": "browser_new_permission"}
   Example: {"download_url": "browser_download"} for download control

3. Add test case in tests/unit/test_tool_registry.py:
   def test_interact_new_action_resolves(self):
       assert resolve_permission_type("browser_interact", {"action": "new_action"}) == "browser_new_permission"

HOW TO ADD CANONICAL PARAMETERS FOR NEW TOOLS:

1. Add to TOOL_CANONICAL_PARAMS: {"tool_name": ["param1", "param2"]}
   Example: {"new_tool": ["url", "method"]} for core functional params only
   Exclude LLM-generated auxiliary fields like "reason" or "description"

2. Add test case in tests/unit/test_canonical_args_hash.py verifying hash stability

HOW TO DECLARE SAFETY METADATA FOR NEW TOOLS:

All built-in tools should be explicitly declared in TOOL_SAFETY_METADATA.
Undeclared tools still get fail-closed defaults (all False), but explicit
declaration improves transparency and self-documentation.

1. Read-only concurrent-safe: SafetyMetadata(is_read_only=True, is_concurrent_safe=True)
2. Concurrent-safe with side effects: SafetyMetadata(is_concurrent_safe=True)
3. Destructive (irreversible): SafetyMetadata(is_destructive=True)
4. Stateful (needs serialization): SafetyMetadata()

5. Add test case in tests/unit/test_tool_registry.py

[INPUT]
- (none — pure static mapping + dynamic resolver rules)

[OUTPUT]
- TOOL_PERMISSION_MAP: concrete tool name → permission type
- BUILTIN_TOOL_NAMES: all known built-in tool names
- TOOL_CANONICAL_PARAMS: tool name → core parameter list
- TOOL_SAFETY_METADATA: tool name → safety attributes (opt-in whitelist)
- resolve_permission_type(): tool name → permission type (with dynamic sub-action and MCP fallback)
- compute_canonical_args_hash(): stable hash for tool arguments (core params only)
- resolve_safety_metadata(): tool name → SafetyMetadata (fail-closed for undeclared tools)

[POS]
Pure functions, no side effects, trivially testable.
Browser tools use dynamic resolution: browser_interact's permission varies
by ``action`` parameter (fill→browser_fill, upload_file→browser_upload, etc.).
MCP tools (``mcp__`` prefixed) and unknown tools both map to ``mcp_invoke``.
Canonical parameter hashing ensures same functional operation produces same hash,
regardless of LLM's wording variations in auxiliary fields.
Safety metadata declares all built-in tools with four categories:
read-only concurrent-safe, concurrent-safe with side effects, destructive,
and stateful. resolve_safety_metadata uses three-level fallback:
built-in static registry → MCP dynamic registry → fail-closed defaults.
Used by safety_dispatcher middleware for concurrency control.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

TOOL_PERMISSION_MAP: dict[str, str] = {
    "bash_code_execute_tool": "code_interpreter",
    "file_read_tool": "file_read",
    "file_write_tool": "file_write",
    "file_edit_tool": "file_write",
    "web_fetch_tool": "net_fetch",
    "grep_tool": "file_read",
    "glob_tool": "file_read",
    "browser_navigate_tool": "browser_navigate",
    "browser_inspect_tool": "browser_read",
    "browser_snapshot_tool": "browser_read",
    "browser_extract_tool": "browser_read",
    "delegate_to_agent_tool": "delegate_agent",
    "delegate_task_tool": "delegate_agent",
    "batch_delegate_tasks_tool": "delegate_agent",
    "cron_manage_tool": "cron_manage",
    "skill_manage_tool": "skill_manage",
    "browser_local_search_tool": "browser_local_data",
    "desktop_inspect_tool": "desktop_capture",
    "desktop_snapshot_tool": "desktop_capture",
    "desktop_interact_tool": "desktop_control",
    "desktop_vision_tool": "desktop_control",
}

BUILTIN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        *TOOL_PERMISSION_MAP,
        "web_search_tool",
        "conversation_search_tool",
        "memory_recall_tool",
        "memory_save_tool",
        "memory_manage_tool",
        "skill_select_tool",
        "skill_discovery_tool",
        "skill_analyze_tool",
        "discover_capability_tool",
        "browser_interact_tool",
        "browser_manage_tool",
        "request_answer_user_tool",
        "render_ui_tool",
        "todo_write",
        "desktop_inspect_tool",
        "desktop_snapshot_tool",
        "desktop_interact_tool",
        "desktop_vision_tool",
        "get_goal_status_tool",
        "update_goal_status_tool",
        "ask_question_tool",
    }
)

# ---------------------------------------------------------------------------
# Tool group mapping — canonical capability-based grouping for SKILL.md
# conditional activation (requires_tool_groups / fallback_for_tool_groups).
# Server-layer ``enabled_builtin_tools`` should reference these group keys.
# ---------------------------------------------------------------------------

TOOL_GROUP_MAP: dict[str, frozenset[str]] = {
    "web": frozenset(
        {
            "web_search_tool",
            "web_fetch_tool",
        }
    ),
    "browser": frozenset(
        {
            "browser_interact_tool",
            "browser_manage_tool",
            "browser_navigate_tool",
            "browser_snapshot_tool",
            "browser_extract_tool",
            "browser_inspect_tool",
            "browser_local_search_tool",
            "browser_execute_script_tool",
            "browser_ask_human_tool",
        }
    ),
    "file_ops": frozenset(
        {
            "file_read_tool",
            "file_write_tool",
            "file_edit_tool",
            "glob_tool",
            "grep_tool",
        }
    ),
    "shell": frozenset(
        {
            "bash_code_execute_tool",
            "bash_process_tool",
        }
    ),
    "computer_use": frozenset(
        {
            "desktop_inspect_tool",
            "desktop_snapshot_tool",
            "desktop_interact_tool",
            "desktop_vision_tool",
        }
    ),
    "memory": frozenset(
        {
            "memory_recall_tool",
            "memory_save_tool",
            "memory_manage_tool",
            "conversation_search_tool",
        }
    ),
    "kanban": frozenset(
        {
            "kanban_show",
            "kanban_complete",
            "kanban_block",
            "kanban_heartbeat",
            "kanban_comment",
            "kanban_add_task",
            "kanban_list_tasks",
            "kanban_update_task",
            "kanban_move_task",
            "kanban_delete_task",
            "kanban_board_summary",
            "kanban_add_dependency",
            "kanban_remove_dependency",
            "kanban_create_board",
            "kanban_list_boards",
            "kanban_get_task",
        }
    ),
    "wiki": frozenset(
        {
            "wiki_query_tool",
            "wiki_compile_tool",
            "wiki_ingest_tool",
            "wiki_maintain_tool",
        }
    ),
    "planning": frozenset({"todo_write"}),
    "answer_tool": frozenset({"request_answer_user_tool"}),
    "canvas": frozenset(
        {
            "canvas_get_state",
            "canvas_get_selection",
            "canvas_insert_element",
        }
    ),
    "render_ui": frozenset({"render_ui_tool"}),
    "image_generation": frozenset({"image_tool"}),
    "video_generation": frozenset({"video_tool"}),
    "tts": frozenset({"tts_generate"}),
}

TOOL_TO_GROUP: dict[str, str] = {tool: group for group, tools in TOOL_GROUP_MAP.items() for tool in tools}

TOOL_GROUP_NAMES: frozenset[str] = frozenset(TOOL_GROUP_MAP)

_INTERACT_ACTION_MAP: dict[str, str] = {
    "fill": "browser_fill",
    "type": "browser_fill",
    "upload_file": "browser_upload",
    "scroll": "browser_scroll",
}

_MANAGE_ACTION_MAP: dict[str, str] = {
    "evaluate": "browser_evaluate",
    "save_session": "browser_session",
    "restore_session": "browser_session",
    "delete_session": "browser_session",
    "wait_for_user": "browser_human_handover",
    "download_url": "browser_download",
}

TOOL_CANONICAL_PARAMS: dict[str, list[str]] = {
    "bash_code_execute_tool": ["command"],
    "file_read_tool": ["path"],
    "file_write_tool": ["path", "content"],
    "file_edit_tool": ["path", "old_string", "new_string"],
    "browser_navigate_tool": ["url"],
    "browser_interact_tool": ["action", "ref", "value"],
    "browser_manage_tool": ["action", "value"],
    "browser_inspect_tool": [],
    "browser_snapshot_tool": [],
    "browser_extract_tool": ["selector"],
    "grep_tool": ["pattern", "path"],
    "glob_tool": ["pattern"],
    "web_fetch_tool": ["url"],
    "web_search_tool": ["query"],
    "memory_save_tool": ["content", "tags"],
    "memory_recall_tool": ["query"],
    "memory_manage_tool": ["action"],
    "skill_select_tool": ["skill_ids"],
    "skill_discovery_tool": ["query"],
    "browser_local_search_tool": ["keywords", "source", "since"],
    "desktop_inspect_tool": [],
    "desktop_snapshot_tool": ["scope", "window_title", "include_screenshot"],
    "desktop_interact_tool": ["ref", "action", "text"],
    "desktop_vision_tool": ["action", "coordinate", "text", "scroll_direction", "start_coordinate"],
}


def compute_canonical_args_hash(tool_name: str, tool_args: dict | None) -> str | None:
    """Compute hash of canonical parameters, ignoring LLM-generated auxiliary fields.

    Only core functional parameters are hashed (e.g., 'command' for bash tools),
    while auxiliary fields like 'reason' or 'description' are excluded.
    This ensures the same functional operation produces the same hash,
    regardless of LLM's wording variations.

    Args:
        tool_name: Tool name (e.g., 'bash_code_execute_tool', 'file_read_tool')
        tool_args: Tool arguments dict

    Returns:
        SHA256[:16] hash of canonical parameters, or None if tool_args is None
    """
    import hashlib
    import json

    if tool_args is None:
        return None

    core_params = TOOL_CANONICAL_PARAMS.get(tool_name)
    if core_params is None:
        canonical = tool_args
    else:
        canonical = {k: v for k, v in tool_args.items() if k in core_params}

    sorted_json = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(sorted_json.encode()).hexdigest()[:16]


def resolve_permission_type(tool_name: str, tool_input: dict[str, object] | None = None) -> str:
    """Resolve a concrete tool name to its abstract permission type.

    Lookup order:
    1. Dynamic resolution for browser_interact/browser_manage (sub-action → fine-grained permission)
    2. Explicit mapping in ``TOOL_PERMISSION_MAP`` (e.g. bash_code_execute_tool → code_interpreter)
    3. Built-in tool with no mapping → keep original name (e.g. web_search_tool)
    4. Unknown tool → ``mcp_invoke`` (MCP tools have dynamic names)
    """
    if tool_input and tool_name == "browser_interact_tool":
        action = str(tool_input.get("action", ""))
        return _INTERACT_ACTION_MAP.get(action, "browser_click")
    if tool_input and tool_name == "browser_manage_tool":
        action = str(tool_input.get("action", ""))
        return _MANAGE_ACTION_MAP.get(action, "browser_manage")
    if tool_name == "desktop_vision_tool":
        if tool_input:
            action = str(tool_input.get("action", ""))
            if action in ("capture", "screenshot", "wait"):
                return "desktop_capture"
        return "desktop_control"
    if tool_name == "desktop_interact_tool":
        return "desktop_control"
    if tool_name == "desktop_inspect_tool":
        return "desktop_capture"
    if tool_name == "desktop_snapshot_tool":
        return "desktop_capture"

    if tool_name in TOOL_PERMISSION_MAP:
        return TOOL_PERMISSION_MAP[tool_name]
    if tool_name in BUILTIN_TOOL_NAMES:
        return tool_name
    # MCP tools use mcp__{server}__{tool} prefix — fast-path before fallback
    if tool_name.startswith("mcp__"):
        return "mcp_invoke"
    return "mcp_invoke"


# ---------------------------------------------------------------------------
# Safety metadata — opt-in whitelist with fail-closed defaults
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SafetyMetadata:
    """Tool safety attributes for concurrency scheduling and sub-agent filtering.

    Defaults are fail-closed: undeclared tools are assumed to be
    non-read-only, concurrency-unsafe, and non-destructive.
    """

    is_read_only: bool = False
    is_concurrent_safe: bool = False
    is_destructive: bool = False
    is_open_world: bool = False
    is_idempotent: bool = False
    taint_label: str | None = None
    taint_extractor: Callable[[dict], str | None] | str | None = None


class MCPAnnotations(TypedDict, total=False):
    """Native MCP tool annotations."""

    readOnlyHint: bool
    idempotentHint: bool
    destructiveHint: bool
    openWorldHint: bool


_PTC_SAFETY_METADATA: dict[str, dict[str, tuple[SafetyMetadata, MCPAnnotations]]] = {}

# Flat index for O(1) lookup by tool_name, consumed by resolve_safety_metadata.
_PTC_TOOL_FLAT_INDEX: dict[str, SafetyMetadata] = {}


def register_ptc_safety_metadata(
    skill_name: str,
    tool_name: str,
    safety_meta: SafetyMetadata,
    annotations: MCPAnnotations,
) -> None:
    """Register dynamically extracted safety metadata for an MCP tool."""
    if skill_name not in _PTC_SAFETY_METADATA:
        _PTC_SAFETY_METADATA[skill_name] = {}
    _PTC_SAFETY_METADATA[skill_name][tool_name] = (safety_meta, annotations)
    _PTC_TOOL_FLAT_INDEX[tool_name] = safety_meta


def get_ptc_safety_metadata(skill_name: str, tool_name: str) -> tuple[SafetyMetadata, MCPAnnotations] | None:
    """Retrieve dynamic safety metadata for an MCP tool."""
    return _PTC_SAFETY_METADATA.get(skill_name, {}).get(tool_name)


def _sanitize_url_for_taint(url: str | None) -> str | None:
    """Sanitize a URL to prevent leaking sensitive query parameters or hashes.

    Extracts only the scheme, netloc, and path.
    """
    if not url:
        return None
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        # Reconstruct without query (?) and fragment (#)
        sanitized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return sanitized
    except Exception:
        # If parsing fails, return a generic string rather than leaking the raw input
        return "invalid_or_redacted_url"


_FAIL_CLOSED_DEFAULTS = SafetyMetadata()

TOOL_SAFETY_METADATA: dict[str, SafetyMetadata] = {
    # Read-only, concurrent-safe tools (all read-only tools are generally idempotent)
    "file_read_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "grep_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "glob_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "browser_inspect_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "browser_snapshot_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=lambda args: _sanitize_url_for_taint(args.get("url")),
    ),
    "browser_extract_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=lambda args: _sanitize_url_for_taint(args.get("url")),
    ),
    "web_search_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=lambda args: f"search_query: {args.get('query', '')}" if args.get("query") else None,
    ),
    "web_fetch_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=lambda args: _sanitize_url_for_taint(args.get("url")),
    ),
    "conversation_search_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "memory_recall_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "todo_write": SafetyMetadata(is_read_only=False, is_concurrent_safe=False, is_idempotent=False),
    "discover_capability_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "skill_discovery_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "skill_select_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "browser_local_search_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "request_answer_user_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "render_ui_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    # Concurrent-safe but not read-only (independent execution contexts)
    "delegate_task_tool": SafetyMetadata(is_concurrent_safe=True),
    "batch_delegate_tasks_tool": SafetyMetadata(is_concurrent_safe=True),
    # CliRuntime uses a single subprocess per backend — parallel turns are unsafe.
    "delegate_to_agent_tool": SafetyMetadata(),
    # Destructive tools (explicit fail-closed: is_concurrent_safe=False)
    "bash_code_execute_tool": SafetyMetadata(is_destructive=True),
    "file_write_tool": SafetyMetadata(is_destructive=True, is_idempotent=True),  # Writing same content is idempotent
    "file_edit_tool": SafetyMetadata(is_destructive=True),
    # Stateful tools (explicit fail-closed: is_concurrent_safe=False)
    "browser_navigate_tool": SafetyMetadata(
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=lambda args: _sanitize_url_for_taint(args.get("url")),
    ),
    "browser_interact_tool": SafetyMetadata(),
    "browser_manage_tool": SafetyMetadata(),
    "cron_manage_tool": SafetyMetadata(),
    "skill_manage_tool": SafetyMetadata(),
    "memory_save_tool": SafetyMetadata(is_idempotent=True),
    "memory_manage_tool": SafetyMetadata(),
    "get_goal_status_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "update_goal_status_tool": SafetyMetadata(),
    "desktop_inspect_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "desktop_snapshot_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "desktop_interact_tool": SafetyMetadata(is_destructive=True),
    "desktop_vision_tool": SafetyMetadata(is_destructive=True),
    "ask_question_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "skill_analyze_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
}


def resolve_safety_metadata(tool_name: str) -> SafetyMetadata:
    """Resolve safety attributes for a tool.

    Three-level fallback:
    1. Built-in tools: ``TOOL_SAFETY_METADATA`` (highest priority)
    2. MCP dynamic tools: ``_PTC_TOOL_FLAT_INDEX`` (populated by ``register_ptc_safety_metadata``)
    3. Fail-closed defaults for unknown tools
    """
    if tool_name in TOOL_SAFETY_METADATA:
        return TOOL_SAFETY_METADATA[tool_name]
    if tool_name in _PTC_TOOL_FLAT_INDEX:
        return _PTC_TOOL_FLAT_INDEX[tool_name]
    return _FAIL_CLOSED_DEFAULTS


from myrm_agent_harness.core.security.tool_registry_safety import check_safety_coverage

_check_safety_coverage = check_safety_coverage
check_safety_coverage()

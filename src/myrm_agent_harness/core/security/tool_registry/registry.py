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
- AUTO_APPROVED_BUILTIN_TOOLS: built-in tool → governance approval reason (audit declaration)
- EXPLICIT_MCP_FALLBACK_TOOLS: built-in tools that intentionally keep mcp_invoke fallback (audit declaration)
- DYNAMICALLY_RESOLVED_TOOL_NAMES: built-in tools resolved by resolve_permission_type() sub-action branches (audit declaration)
- AUTO_APPROVE_REASONS: valid governance reason categories
- RULESET_COVERAGE_WHITELIST: permission type → governance approval reason (no DEFAULT_RULESET rule)
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
    "subagent_control_tool": "delegate_agent",
    "cron_manage_tool": "cron_manage",
    "skill_manage_tool": "skill_manage",
    "desktop_snapshot_tool": "desktop_capture",
    "desktop_interact_tool": "desktop_control",
    "desktop_vision_tool": "desktop_control",
}

BUILTIN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        *TOOL_PERMISSION_MAP,
        "web_search_tool",
        "memory_search_tool",
        "memory_save_tool",
        "memory_manage_tool",
        "skill_select_tool",
        "skill_market_tool",
        "skill_search_tool",
        "browser_interact_tool",
        "browser_manage_tool",
        "request_answer_user_tool",
        "render_ui_tool",
        "update_ui_data_tool",
        "todo_write",
        "desktop_snapshot_tool",
        "desktop_interact_tool",
        "desktop_vision_tool",
        "complete_goal_tool",
        "ask_question_tool",
        "bash_process_tool",
        "browser_ask_human_tool",
        "kanban_show",
        "kanban_complete",
        "kanban_block",
        "kanban_heartbeat",
        "kanban_comment",
        "kanban_attach",
        "kanban_add_task",
        "kanban_list_tasks",
        "kanban_unblock",
        "kanban_cancel_task",
        "kanban_retry_task",
        "wiki_ingest_tool",
        "wiki_query_tool",
        "wiki_apply_tool",
    }
)

# ---------------------------------------------------------------------------
# Governance coverage — audit declarations for built-in tools.
#
# Built-in tools that are NOT in TOOL_PERMISSION_MAP fall through to
# resolve_permission_type() → their own tool name, which has no explicit rule
# in DEFAULT_RULESET, so they are approved by the ("*", "*", ALLOW) baseline.
# This fallback is intentional for the tools declared below. The declaration is
# audit metadata consumed by the CI governance check
# (scripts/validate_tool_registry.py): every built-in tool must either be
# permission-mapped, dynamically resolved, or declared here with a valid
# reason, so a newly added tool can never silently bypass governance.
#
# These declarations do NOT change runtime permission resolution.
# ---------------------------------------------------------------------------

AUTO_APPROVE_REASONS: frozenset[str] = frozenset(
    {
        "read_only",  # pure reads, no side effects
        "internal",  # framework-internal control signal, no user data exposure
        "display",  # user-facing rendering / progress UI
        "user_visible",  # side effects directly visible to and driven by the user
        "channel_guarded",  # blocked on non-web channels by the capability fence
    }
)

AUTO_APPROVED_BUILTIN_TOOLS: dict[str, str] = {
    "ask_question_tool": "user_visible",  # interactive clarification, user sees every question
    "browser_ask_human_tool": "user_visible",  # in-page HITL prompt (2FA/CAPTCHA), user sees every prompt
    "complete_goal_tool": "internal",  # goal-state marking signal
    "kanban_add_task": "user_visible",  # kanban task creation, user opt-in + board UI
    "kanban_attach": "user_visible",  # attach files/notes to kanban task
    "kanban_block": "user_visible",  # mark task blocked
    "kanban_cancel_task": "user_visible",  # cancel running kanban task
    "kanban_comment": "user_visible",  # progress comments on kanban task
    "kanban_complete": "user_visible",  # mark task done
    "kanban_heartbeat": "user_visible",  # keep-alive heartbeat for long-running task
    "kanban_list_tasks": "read_only",  # list kanban tasks, pure read
    "kanban_retry_task": "user_visible",  # retry failed kanban task
    "kanban_show": "read_only",  # show kanban task detail, pure read
    "kanban_unblock": "user_visible",  # unblock kanban task
    "memory_manage_tool": "user_visible",  # memory housekeeping, user-visible + audited
    "memory_save_tool": "user_visible",  # memory writes, user-visible + scan-audited
    "memory_search_tool": "read_only",
    "render_ui_tool": "display",
    "request_answer_user_tool": "internal",  # answer-phase gating signal
    "skill_market_tool": "user_visible",  # skill install from market, trust-scanned + user-visible
    "skill_search_tool": "read_only",
    "skill_select_tool": "read_only",
    "todo_write": "display",  # progress plan UI
    "update_ui_data_tool": "display",
    "web_search_tool": "read_only",
    "wiki_apply_tool": "user_visible",  # apply compiled wiki entry into store
    "wiki_ingest_tool": "user_visible",  # ingest external content into wiki
    "wiki_query_tool": "read_only",  # wiki retrieval, pure read
}

# Built-in tools that intentionally keep the `mcp_invoke` fallback (runtime ASK)
# instead of being promoted to their own name (runtime ALLOW). These tools have
# real external side effects or high blast radius, so they must NOT be added to
# BUILTIN_TOOL_NAMES — doing so would silently flip their runtime baseline to
# ALLOW. The governance gate (scripts/validate_tool_registry.py) treats this set
# as a valid third governance state, so it does not flag them as uncovered.
EXPLICIT_MCP_FALLBACK_TOOLS: frozenset[str] = frozenset(
    {
        "browser_execute_script_tool",  # arbitrary JS execution — keep ASK (plus in-tool HITL for privileged APIs)
        "send_teammate_message_tool",  # cross-agent message dispatch — external side effect, keep ASK
    }
)

# Built-in tools whose permission type is resolved dynamically by
# ``resolve_permission_type()`` (sub-action → fine-grained permission). They may
# also carry a TOOL_PERMISSION_MAP entry as a static fallback for sub-actions
# without fine-grained mapping. SSOT consumed by the governance gate
# (scripts/validate_tool_registry.py) — the gate must not re-declare its own
# copy, otherwise the two lists drift and a removed dynamic branch would be
# silently treated as still-governed (ASK → baseline ALLOW).
DYNAMICALLY_RESOLVED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "bash_process_tool",
        "browser_interact_tool",
        "browser_manage_tool",
        "desktop_snapshot_tool",
        "desktop_interact_tool",
        "desktop_vision_tool",
    }
)

# Permission types resolved by TOOL_PERMISSION_MAP that have no explicit rule in
# DEFAULT_RULESET and therefore fall back to the baseline ALLOW. Declared here so
# the governance check can fail-closed when a new permission type is introduced
# without an explicit ruleset rule or declaration.
RULESET_COVERAGE_WHITELIST: dict[str, str] = {
    "browser_read": "read_only",  # browser_inspect/snapshot/extract — pure page reads
    "desktop_capture": "channel_guarded",  # desktop screenshots — local GUI only, excluded from IM/CRON by capability fence
    "net_fetch": "read_only",  # web_fetch_tool — SSRF-guarded at the sandbox layer
}

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
            "desktop_snapshot_tool",
            "desktop_interact_tool",
            "desktop_vision_tool",
        }
    ),
    "memory": frozenset(
        {
            "memory_search_tool",
            "memory_save_tool",
            "memory_manage_tool",
        }
    ),
    # Metadata-only group: conversation_search_tool is LAYER_EXEMPT (tool_registry_config).
    # Product Turn1 binds memory_search_tool(corpus=sessions), not this factory tool name.
    "conversation_history": frozenset(
        {
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
            "kanban_attach",
            "kanban_add_task",
            "kanban_list_tasks",
            "kanban_unblock",
        }
    ),
    "wiki": frozenset(
        {
            "wiki_query_tool",
            "wiki_ingest_tool",
            "wiki_apply_tool",
        }
    ),
    "planning": frozenset({"todo_write"}),
    "answer_tool": frozenset({"request_answer_user_tool"}),
    "render_ui": frozenset({"render_ui_tool", "update_ui_data_tool"}),
    "structured_clarify": frozenset({"ask_question_tool"}),
    "cron": frozenset({"cron_manage_tool"}),
    "image_generation": frozenset({"image_tool"}),
    "video_generation": frozenset({"video_tool"}),
    "tts": frozenset({"tts_generate"}),
    "external_cli": frozenset({"delegate_to_agent_tool"}),
}

TOOL_TO_GROUP: dict[str, str] = {
    tool: group for group, tools in TOOL_GROUP_MAP.items() for tool in tools
}

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
    "download_url": "browser_download",
}

TOOL_CANONICAL_PARAMS: dict[str, list[str]] = {
    "bash_code_execute_tool": ["command"],
    "bash_process_tool": ["action", "pid", "data"],
    "file_read_tool": ["path"],
    "file_write_tool": ["path", "content"],
    "file_edit_tool": ["path", "edits"],
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
    "memory_search_tool": ["query"],
    "memory_manage_tool": ["action"],
    "skill_select_tool": ["skill_names"],
    "skill_market_tool": ["action", "skill_id"],
    "skill_manage_tool": ["action", "name"],
    "skill_search_tool": ["query"],
    "desktop_snapshot_tool": ["scope", "app_name", "include_screenshot"],
    "desktop_interact_tool": ["ref", "action", "text"],
    "desktop_vision_tool": [
        "action",
        "coordinate",
        "text",
        "scroll_direction",
        "start_coordinate",
    ],
    "ask_question_tool": [],
    "complete_goal_tool": [],
    "cron_manage_tool": ["action", "job_id", "name_filter"],
    "delegate_task_tool": ["mode", "agent_type"],
    "delegate_to_agent_tool": ["agent_name"],
    "render_ui_tool": [],
    "request_answer_user_tool": [],
    "subagent_control_tool": ["action", "task_id"],
    "todo_write": ["merge"],
    "update_ui_data_tool": ["surface_id"],
}


def compute_canonical_args_hash(
    tool_name: str, tool_args: dict[str, object] | None
) -> str | None:
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


def resolve_permission_type(
    tool_name: str, tool_input: dict[str, object] | None = None
) -> str:
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
    if tool_input and tool_name == "bash_process_tool":
        action = str(tool_input.get("action", ""))
        if action in ("write_stdin", "submit_stdin", "close_stdin", "kill"):
            return "shell_exec"
        return "bash_process_tool"
    if tool_name == "desktop_vision_tool":
        if tool_input:
            action = str(tool_input.get("action", ""))
            if action in ("capture", "screenshot", "wait"):
                return "desktop_capture"
        return "desktop_control"
    if tool_name == "desktop_interact_tool":
        return "desktop_control"
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
    taint_extractor: Callable[[dict[str, object]], str | None] | str | None = None


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


def get_ptc_safety_metadata(
    skill_name: str, tool_name: str
) -> tuple[SafetyMetadata, MCPAnnotations] | None:
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


def _taint_url_from_args(args: dict[str, object]) -> str | None:
    """Extract and sanitize the ``url`` arg for taint labeling (non-str values dropped)."""
    url = args.get("url")
    return _sanitize_url_for_taint(url if isinstance(url, str) else None)


_FAIL_CLOSED_DEFAULTS = SafetyMetadata()

TOOL_SAFETY_METADATA: dict[str, SafetyMetadata] = {
    # Read-only, concurrent-safe tools (all read-only tools are generally idempotent)
    "file_read_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "grep_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "glob_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "browser_inspect_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "browser_snapshot_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=_taint_url_from_args,
    ),
    "browser_extract_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=_taint_url_from_args,
    ),
    "web_search_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=lambda args: (
            f"search_query: {args.get('query', '')}" if args.get("query") else None
        ),
    ),
    "web_fetch_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=_taint_url_from_args,
    ),
    "memory_search_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "todo_write": SafetyMetadata(
        is_read_only=False, is_concurrent_safe=False, is_idempotent=False
    ),
    "skill_search_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "skill_market_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "skill_select_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "request_answer_user_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "render_ui_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "update_ui_data_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    # Concurrent-safe but not read-only (independent execution contexts)
    "delegate_task_tool": SafetyMetadata(is_concurrent_safe=True),
    "subagent_control_tool": SafetyMetadata(is_concurrent_safe=True),
    # CliRuntime uses a single subprocess per backend — parallel turns are unsafe.
    "delegate_to_agent_tool": SafetyMetadata(),
    # Destructive tools (explicit fail-closed: is_concurrent_safe=False)
    "bash_code_execute_tool": SafetyMetadata(is_destructive=True),
    "bash_process_tool": SafetyMetadata(),
    "file_write_tool": SafetyMetadata(
        is_destructive=True, is_idempotent=True
    ),  # Writing same content is idempotent
    "file_edit_tool": SafetyMetadata(is_destructive=True),
    # Stateful tools (explicit fail-closed: is_concurrent_safe=False)
    "browser_navigate_tool": SafetyMetadata(
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=_taint_url_from_args,
    ),
    "browser_interact_tool": SafetyMetadata(),
    "browser_manage_tool": SafetyMetadata(),
    "cron_manage_tool": SafetyMetadata(),
    "skill_manage_tool": SafetyMetadata(),
    "memory_save_tool": SafetyMetadata(is_idempotent=True),
    "memory_manage_tool": SafetyMetadata(),
    "complete_goal_tool": SafetyMetadata(),
    "desktop_snapshot_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "desktop_interact_tool": SafetyMetadata(is_destructive=True),
    "desktop_vision_tool": SafetyMetadata(is_destructive=True),
    "ask_question_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=False, is_idempotent=True
    ),
    # kanban worker/orchestrator tools — stateful board mutations, serialized by store lock
    "kanban_show": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "kanban_list_tasks": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "kanban_add_task": SafetyMetadata(),
    "kanban_attach": SafetyMetadata(),
    "kanban_block": SafetyMetadata(),
    "kanban_cancel_task": SafetyMetadata(),
    "kanban_comment": SafetyMetadata(),
    "kanban_complete": SafetyMetadata(),
    "kanban_heartbeat": SafetyMetadata(),
    "kanban_retry_task": SafetyMetadata(),
    "kanban_unblock": SafetyMetadata(),
    # wiki knowledge-base tools — query read-only; mutations stateful
    "wiki_query_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=True, is_idempotent=True
    ),
    "wiki_apply_tool": SafetyMetadata(),
    "wiki_ingest_tool": SafetyMetadata(),
    # browser HITL prompt — user-visible, no side effects beyond asking
    "browser_ask_human_tool": SafetyMetadata(
        is_read_only=True, is_concurrent_safe=False, is_idempotent=True
    ),
    # explicit mcp_invoke fallback tools — declared for module-load gate transparency
    "browser_execute_script_tool": SafetyMetadata(),
    "send_teammate_message_tool": SafetyMetadata(),
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


from .safety import check_safety_coverage  # noqa: E402

_check_safety_coverage = check_safety_coverage
check_safety_coverage()

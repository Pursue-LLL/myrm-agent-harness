"""Built-in tool safety table: SafetyMetadata model and TOOL_SAFETY_METADATA.

[INPUT]
- taint_extractors::taint_url_from_args, taint_secret_file_from_args, taint_secret_command_from_args (POS: tool-argument taint labelers wired into the table)

[OUTPUT]
- SafetyMetadata: fail-closed safety attributes for concurrency scheduling and sub-agent filtering
- TOOL_SAFETY_METADATA: built-in tool name → SafetyMetadata (opt-in whitelist)
- _FAIL_CLOSED_DEFAULTS: metadata applied to undeclared tools

[POS]
Static data split out of ``registry.py`` to keep it under the file line limit.
``registry.py`` re-exports every symbol so the flat import surface is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .taint_extractors import (
    taint_secret_command_from_args,
    taint_secret_file_from_args,
    taint_url_from_args,
)

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
    is_third_party_visible: bool = False
    is_open_world: bool = False
    is_idempotent: bool = False
    taint_label: str | None = None
    taint_extractor: Callable[[dict[str, object]], str | None] | str | None = None


_FAIL_CLOSED_DEFAULTS = SafetyMetadata()

TOOL_SAFETY_METADATA: dict[str, SafetyMetadata] = {
    # Read-only, concurrent-safe tools (all read-only tools are generally idempotent)
    "file_read_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="secret",
        taint_extractor=taint_secret_file_from_args,
    ),
    "grep_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "glob_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "browser_inspect_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "browser_snapshot_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=taint_url_from_args,
    ),
    "browser_extract_tool": SafetyMetadata(
        is_read_only=True,
        is_concurrent_safe=True,
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=taint_url_from_args,
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
        taint_extractor=taint_url_from_args,
    ),
    "memory_search_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "todo_write": SafetyMetadata(is_read_only=False, is_concurrent_safe=False, is_idempotent=False),
    "working_memory_manage_tool": SafetyMetadata(is_read_only=False, is_concurrent_safe=False, is_idempotent=False),
    "skill_search_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "skill_market_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "skill_select_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "request_answer_user_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    # Concurrent-safe but not read-only (independent execution contexts)
    "delegate_task_tool": SafetyMetadata(is_concurrent_safe=True),
    "subagent_control_tool": SafetyMetadata(is_concurrent_safe=True),
    # CliRuntime uses a single subprocess per backend — parallel turns are unsafe.
    "invoke_acp_agent_tool": SafetyMetadata(),
    # Destructive tools (explicit fail-closed: is_concurrent_safe=False)
    "bash_code_execute_tool": SafetyMetadata(
        is_destructive=True,
        taint_label="secret",
        taint_extractor=taint_secret_command_from_args,
    ),
    "bash_process_tool": SafetyMetadata(),
    "file_write_tool": SafetyMetadata(is_destructive=True, is_idempotent=True),  # Writing same content is idempotent
    "file_edit_tool": SafetyMetadata(is_destructive=True),
    # Stateful tools (explicit fail-closed: is_concurrent_safe=False)
    "browser_navigate_tool": SafetyMetadata(
        is_idempotent=True,
        taint_label="external_network",
        taint_extractor=taint_url_from_args,
    ),
    "browser_interact_tool": SafetyMetadata(),
    "browser_manage_tool": SafetyMetadata(),
    "cron_manage_tool": SafetyMetadata(),
    "skill_manage_tool": SafetyMetadata(),
    "memory_save_tool": SafetyMetadata(is_idempotent=True),
    "memory_manage_tool": SafetyMetadata(),
    "complete_goal_tool": SafetyMetadata(),
    "desktop_snapshot_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "desktop_interact_tool": SafetyMetadata(is_destructive=True),
    "desktop_vision_tool": SafetyMetadata(is_destructive=True),
    "mobile_snapshot_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "mobile_interact_tool": SafetyMetadata(is_destructive=True),
    "mobile_global_tool": SafetyMetadata(is_destructive=True),
    "ask_question_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=False, is_idempotent=True),
    # kanban worker/orchestrator tools — stateful board mutations, serialized by store lock
    "kanban_show": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "kanban_list_tasks": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "kanban_add_task": SafetyMetadata(),
    "kanban_attach": SafetyMetadata(),
    "kanban_block": SafetyMetadata(),
    "kanban_cancel_task": SafetyMetadata(),
    "kanban_comment": SafetyMetadata(),
    "kanban_complete": SafetyMetadata(),
    "kanban_heartbeat": SafetyMetadata(),
    "kanban_retry_task": SafetyMetadata(),
    "kanban_revise_plan": SafetyMetadata(),
    "kanban_unblock": SafetyMetadata(),
    # wiki knowledge-base tools — query read-only; mutations stateful
    "wiki_query_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    "wiki_apply_tool": SafetyMetadata(),
    "wiki_ingest_tool": SafetyMetadata(),
    # browser HITL prompt — user-visible, no side effects beyond asking
    "browser_ask_human_tool": SafetyMetadata(is_read_only=True, is_concurrent_safe=False, is_idempotent=True),
    # explicit mcp_invoke fallback tools — declared for module-load gate transparency
    "browser_execute_script_tool": SafetyMetadata(),
    "send_teammate_message_tool": SafetyMetadata(is_third_party_visible=True),
    # pure read over the in-memory message history
    "refetch_historical_turn": SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True),
    # stateful per-turn rate limiter + SSE push: not idempotent, not concurrency-safe
    "send_user_message_async": SafetyMetadata(),
}

"""Governance coverage declarations for built-in tools.

Built-in tools that are NOT in ``TOOL_PERMISSION_MAP`` fall through to
``resolve_permission_type()`` → their own tool name, which has no explicit rule in
``DEFAULT_RULESET``, so they are approved by the ``("*", "*", ALLOW)`` baseline. That
fallback is intentional for the tools declared here. The declaration is audit metadata
consumed by the CI governance check (``scripts/validate_tool_registry.py``): every
built-in tool must either be permission-mapped, dynamically resolved, or declared here
with a valid reason, so a newly added tool can never silently bypass governance.

These declarations do NOT change runtime permission resolution.

[OUTPUT]
- AUTO_APPROVE_REASONS: valid governance reason categories
- AUTO_APPROVED_BUILTIN_TOOLS: built-in tool → governance approval reason
- EXPLICIT_MCP_FALLBACK_TOOLS: tools that intentionally keep the mcp_invoke ASK baseline
- DYNAMICALLY_RESOLVED_TOOL_NAMES: tools resolved by sub-action inside resolve_permission_type()
- RULESET_COVERAGE_WHITELIST: permission type → approval reason when DEFAULT_RULESET has no rule

[POS]
Audit-only governance metadata, split out of ``registry.py`` to keep that module about
resolution logic. ``registry.py`` re-exports every symbol so the flat import surface is
unchanged.
"""

from __future__ import annotations

# Governance coverage — audit declarations for built-in tools.

# Built-in tools that are NOT in TOOL_PERMISSION_MAP fall through to
# resolve_permission_type() → their own tool name, which has no explicit rule
# in DEFAULT_RULESET, so they are approved by the ("*", "*", ALLOW) baseline.
# This fallback is intentional for the tools declared below. The declaration is
# audit metadata consumed by the CI governance check
# (scripts/validate_tool_registry.py): every built-in tool must either be
# permission-mapped, dynamically resolved, or declared here with a valid
# reason, so a newly added tool can never silently bypass governance.

# These declarations do NOT change runtime permission resolution.


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
    "kanban_revise_plan": "user_visible",  # orchestrator plan revision, user-visible
    "kanban_show": "read_only",  # show kanban task detail, pure read
    "kanban_unblock": "user_visible",  # unblock kanban task
    "memory_manage_tool": "user_visible",  # memory housekeeping, user-visible + audited
    "memory_save_tool": "user_visible",  # memory writes, user-visible + scan-audited
    "memory_search_tool": "read_only",
    "request_answer_user_tool": "internal",  # answer-phase gating signal
    "skill_market_tool": "user_visible",  # skill install from market, trust-scanned + user-visible
    "skill_search_tool": "read_only",
    "skill_select_tool": "read_only",
    "todo_write": "display",  # progress plan UI
    "web_search_tool": "read_only",
    "working_memory_manage_tool": "display",  # in-session workbench progress, no external side effects
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
        "refetch_historical_turn",  # selectively wired history reader; keeps its current ASK baseline until promoted
        "send_user_message_async",  # agent-to-user push (rate-limited 3/turn); keeps its current ASK baseline until promoted
        # Profile-mounted tools (not bound by the general agent's Turn1 surface), so they
        # are not in BUILTIN_TOOL_NAMES and keep the ASK baseline until promoted.
        "manage_todo_plan",  # shared plan store writes for delegated sub-agents — keep ASK
        "read_todo_hud",  # reads the shared plan HUD of a session — keep ASK
        "inspect_agent_session",  # reads another agent session's status/logs — cross-session read, keep ASK
        "instruct_agent",  # injects steering into another running session — cross-session write, keep ASK
        "list_mesh_devices",  # enumerates registered edge devices — infrastructure topology, keep ASK
        "dispatch_node_command",  # runs a command on an edge device — remote execution, keep ASK
        "fetch_node_telemetry",  # reads live telemetry from an edge device — infrastructure read, keep ASK
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

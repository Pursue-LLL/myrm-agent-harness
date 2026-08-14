"""Effectful tool detection SSOT for completion-related guards.

Consumed by the Mixed Message Guard (which tool_calls must be preserved)
and the server-side Cron post-run verification (which runs need an
adversarial-reviewer pass). Classification order:

1. Static alias sets are authoritative (`_MUTATION_TOOLS`,
   `_INTERACTION_UI_TOOLS`).
2. Everything else resolves via registry safety metadata with a fail-closed
   default: unknown tools are assumed effectful, since a side effect must
   never go unverified.

[INPUT]
- core.security.tool_registry::resolve_safety_metadata (POS: tool safety metadata incl. MCP readOnlyHint)

[OUTPUT]
- is_mutating_tool(): True when the tool mutates workspace or external state
"""

from __future__ import annotations

from myrm_agent_harness.core.security.tool_registry import resolve_safety_metadata

_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        # 写/执行/管理类（会改变工作区或外部状态）
        "write_file",
        "create_file",
        "edit_file",
        "delete_file",
        "file_write_tool",
        "file_edit_tool",
        "file_create_tool",
        "execute_command",
        "run_terminal",
        "bash_code_execute_tool",
        "send_message",
        "git_commit",
        "git_push",
        "apply_diff",
        "delegate_task_tool",
        "spawn_subagent",
        "request_answer_user_tool",
        "answer_user",
        "finish",
        "complete_task",
        "browser_navigate_tool",
        "browser_click_tool",
        "browser_type_tool",
        "skill_manage_tool",
        "skill_market_tool",  # install/uninstall/install_from_url 写入技能库，registry 只读标注但实为变异
        "kanban_manage_tool",
        "cron_manage_tool",
    }
)

# 交互/UI 承载类：registry 标只读，但剥离会丢失用户可见功能（提问/授权/渲染/人类接管）
_INTERACTION_UI_TOOLS: frozenset[str] = frozenset(
    {
        "ask_question_tool",
        "request_directory_tool",
        "render_ui_tool",
        "update_ui_data_tool",
        "browser_ask_human_tool",
    }
)


def is_mutating_tool(tool_name: str) -> bool:
    """Return True when the tool mutates workspace or external state (effectful).

    SSOT used by Cron post-run verification to decide whether a run needs an
    adversarial-reviewer pass. The static alias set is authoritative; everything
    else resolves via registry metadata (fail-closed: unknown tools assumed
    effectful, since a side effect must never go unverified).
    """
    if tool_name in _MUTATION_TOOLS:
        return True
    return not resolve_safety_metadata(tool_name).is_read_only


__all__ = ["is_mutating_tool"]

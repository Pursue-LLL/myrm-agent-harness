"""工具名称映射 - Claude Code ↔ 内部工具名

提供 Claude Code 简短工具名（Read, Write）与内部描述性工具名（file_read_tool）的双向映射。

[INPUT]
- (none)

[OUTPUT]
- map_to_claude_tool_name: Args:
- map_from_claude_tool_name: Args:
- should_trigger_hook: Args:

[POS]
Provides map_to_claude_tool_name, map_from_claude_tool_name, should_trigger_hook.
"""

# Claude Code → Myrm Agent Harness (internal tool names)
CLAUDE_TO_OUR_MAPPING: dict[str, str] = {
    "Read": "file_read_tool",
    "Write": "file_write_tool",
    "Edit": "file_edit_tool",
    "Glob": "glob_tool",
    "Grep": "grep_tool",
    "Bash": "bash_code_execute_tool",
    "SkillSelect": "skill_select_tool",
    "WebSearch": "web_search_tool",
    "WebFetch": "web_fetch_tool",
    "Planner": "planner_tool",
}

# Myrm Agent Harness → Claude Code（反向映射）
OUR_TO_CLAUDE_MAPPING: dict[str, str] = {v: k for k, v in CLAUDE_TO_OUR_MAPPING.items()}


def map_to_claude_tool_name(our_tool_name: str) -> str:
    """将我们的工具名映射为 Claude Code 工具名

    Args:
        our_tool_name: 我们的工具名（如 file_read_tool）

    Returns:
        Claude Code 工具名（如 Read），如果没有映射则返回原名称
    """
    return OUR_TO_CLAUDE_MAPPING.get(our_tool_name, our_tool_name)


def map_from_claude_tool_name(claude_tool_name: str) -> str:
    """将 Claude Code 工具名映射为我们的工具名

    Args:
        claude_tool_name: Claude Code 工具名（如 Read）

    Returns:
        我们的工具名（如 file_read_tool），如果没有映射则返回原名称
    """
    return CLAUDE_TO_OUR_MAPPING.get(claude_tool_name, claude_tool_name)


def should_trigger_hook(hook_tool_names: list[str] | None, actual_tool_name: str) -> bool:
    """检查 Hook 是否应该触发（支持两种格式的工具名）

    Args:
        hook_tool_names: Hook 定义中的工具名列表（可能是 Claude 格式或我们的格式）
        actual_tool_name: 实际调用的工具名（我们的格式）

    Returns:
        是否应该触发
    """
    if not hook_tool_names:
        return True  # 没有限定工具名，总是触发

    # 支持两种格式匹配
    claude_name = map_to_claude_tool_name(actual_tool_name)

    return actual_tool_name in hook_tool_names or claude_name in hook_tool_names

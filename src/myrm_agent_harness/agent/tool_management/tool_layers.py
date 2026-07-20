"""工具层级定义 - 缓存友好的工具排序基础

1. 本文件的 INPUT/OUTPUT/POS 注释
3. agent/context_management/PROMPT_CACHE_PRACTICE.md §2.1 工具分层排序

[INPUT]
(none — pure enum + dict, no external deps)

[OUTPUT]
- ToolLayer: 工具层级枚举(CORE=1, COMMON=2, EXTENDED=3)
- register_tool_layer(): 注册工具到指定层级
- get_tool_layer(): 获取工具的层级
- is_registered_action_tool(): 判断工具名是否在 Action Tool SSOT 中

[POS]
Tool layer priority registry. Defines CORE/COMMON/EXTENDED three-tier tool priorities used by ToolRegistry for ordering.

"""

from enum import IntEnum


class ToolLayer(IntEnum):
    """工具层级定义 - 数值越小越靠前

    设计目标:最大化 Prompt Cache 命中率

    层级说明:
    - CORE: 核心工具,始终存在,不可关闭
    - COMMON: 通用工具,默认存在,前端可控制开关
    - EXTENDED: 扩展工具,按需加载或定义始终发送
    """

    CORE = 1
    COMMON = 2
    EXTENDED = 3


# 工具层级注册表
#
# 设计原则:
# 1. 始终加载的工具放 CORE,永远在最前面,缓存稳定
# 2. 默认开启但可关的工具放 COMMON,在中间
# 3. 按需加载的工具放 EXTENDED,在最后,变化只影响自己
#
# 排序规则:按层级排序; COMMON 层内 memory 组优先于 web_search，其余按名称字母序
# 缓存原理:Prompt Cache 是前缀匹配,CORE 工具放最前面可保证永远被缓存
#
# 工具名称必须与 @tool() 装饰器中声明的名称完全一致
#
# 架构边界:此处登记 harness 框架自有工具。业务层 vendor 集成 tool（如 x_search_tool）
# 在 myrm-agent-server 通过 skill-gated Turn1 注册,以维持框架-业务层分离原则。
_TOOL_LAYERS: dict[str, ToolLayer] = {
    # ============================================================
    # CORE - 通用 Agent 基线工具（无条件 Turn1 eager，前端无开关）
    # file/bash/web_fetch/glob/grep；Fast 模式仍由 converter 关闭 file/bash
    # ============================================================
    "web_fetch_tool": ToolLayer.CORE,
    "bash_code_execute_tool": ToolLayer.CORE,
    "file_edit_tool": ToolLayer.CORE,
    "file_read_tool": ToolLayer.CORE,
    "file_write_tool": ToolLayer.CORE,
    "glob_tool": ToolLayer.CORE,
    "grep_tool": ToolLayer.CORE,
    # ============================================================
    # COMMON - 默认开启但用户可在 GUI 关闭（放中间；组内 memory 优先于 web_search）
    # ============================================================
    "todo_write": ToolLayer.COMMON,
    "web_search_tool": ToolLayer.COMMON,
    "memory_search_tool": ToolLayer.COMMON,
    "memory_save_tool": ToolLayer.COMMON,
    "memory_manage_tool": ToolLayer.COMMON,
    # ============================================================
    # EXTENDED - 按需加载或低频辅助工具(放最后,变化不影响前面的缓存)
    # ============================================================
    # --- ACP（Agent Communication Protocol）---
    "delegate_to_agent_tool": ToolLayer.EXTENDED,
    # --- Bash 后台进程（discoverable；stable index + invoke）---
    "bash_process_tool": ToolLayer.EXTENDED,
    # --- 浏览器工具 ---
    "browser_extract_tool": ToolLayer.EXTENDED,
    "browser_inspect_tool": ToolLayer.EXTENDED,
    "browser_interact_tool": ToolLayer.EXTENDED,
    "browser_manage_tool": ToolLayer.EXTENDED,
    "browser_navigate_tool": ToolLayer.EXTENDED,
    "browser_execute_script_tool": ToolLayer.EXTENDED,
    "browser_ask_human_tool": ToolLayer.EXTENDED,
    "browser_snapshot_tool": ToolLayer.EXTENDED,
    # --- 计算机操作工具 ---
    "desktop_snapshot_tool": ToolLayer.EXTENDED,
    "desktop_interact_tool": ToolLayer.EXTENDED,
    "desktop_vision_tool": ToolLayer.EXTENDED,
    # --- Cron 定时任务 ---
    "cron_manage_tool": ToolLayer.EXTENDED,
    # --- Goal 工具 ---
    "complete_goal_tool": ToolLayer.EXTENDED,
    # --- 交互工具 ---
    "ask_question_tool": ToolLayer.EXTENDED,
    "render_ui_tool": ToolLayer.EXTENDED,
    "update_ui_data_tool": ToolLayer.EXTENDED,
    "request_answer_user_tool": ToolLayer.EXTENDED,
    # --- 看板 (Worker tools) ---
    "kanban_show": ToolLayer.EXTENDED,
    "kanban_complete": ToolLayer.EXTENDED,
    "kanban_block": ToolLayer.EXTENDED,
    "kanban_heartbeat": ToolLayer.EXTENDED,
    "kanban_comment": ToolLayer.EXTENDED,
    "kanban_attach": ToolLayer.EXTENDED,
    # --- 看板 (Orchestrator tools) ---
    "kanban_add_task": ToolLayer.EXTENDED,
    "kanban_list_tasks": ToolLayer.EXTENDED,
    "kanban_unblock": ToolLayer.EXTENDED,
    # --- 记忆工具（search/save/manage → COMMON；sessions/wiki 通过 corpus ACL）---
    "conversation_search_tool": ToolLayer.EXTENDED,
    # --- 技能工具 ---
    "discover_capability_tool": ToolLayer.EXTENDED,
    "skill_discovery_tool": ToolLayer.EXTENDED,
    "skill_manage_tool": ToolLayer.EXTENDED,
    "skill_select_tool": ToolLayer.EXTENDED,
    # --- Sub-Agent 管理 ---
    "delegate_task_tool": ToolLayer.EXTENDED,
    "subagent_control_tool": ToolLayer.EXTENDED,
    "send_teammate_message_tool": ToolLayer.EXTENDED,
    # --- Wiki 知识库 ---
    "wiki_ingest_tool": ToolLayer.EXTENDED,
    "wiki_query_tool": ToolLayer.EXTENDED,
    "wiki_compile_tool": ToolLayer.EXTENDED,
    "wiki_maintain_tool": ToolLayer.EXTENDED,
}


# COMMON 层组内排序：高频默认能力簇优先，单工具开关次之（组内仍按 name 稳定排序）
_COMMON_LAYER_SORT_RANK: dict[str, int] = {
    "memory_manage_tool": 0,
    "memory_search_tool": 1,
    "memory_save_tool": 2,
    "web_search_tool": 10,
    "todo_write": 30,
}


def get_tool_registry_sort_key(tool_name: str, layer: ToolLayer) -> tuple[int, int, str]:
    """Cache-friendly registry sort key: layer → COMMON group rank → name."""
    if layer == ToolLayer.COMMON:
        group_rank = _COMMON_LAYER_SORT_RANK.get(tool_name, 50)
        return (int(layer), group_rank, tool_name)
    return (int(layer), 0, tool_name)


def get_tool_layer(tool_name: str) -> ToolLayer:
    """获取工具层级

    [核心架构约束]:保护大模型 Prompt Prefix Cache
    所有动态挂载的外部工具(特别是 MCP 提供的工具,如 github_search 等)
    必须强制路由到 EXTENDED 层级(Prompt尾部).
    这能确保前部巨大的 System Prompt 和核心通用工具不被打乱,缓存命中率锁定在100%.

    Args:
        tool_name: 工具名称

    Returns:
        工具层级,未注册的工具(含所有 MCP 工具)默认为 EXTENDED(放在最后)
    """
    return _TOOL_LAYERS.get(tool_name, ToolLayer.EXTENDED)


def is_registered_action_tool(tool_name: str) -> bool:
    """Return True when *tool_name* is registered in the Action Tool SSOT."""
    return tool_name in _TOOL_LAYERS


def register_tool_layer(tool_name: str, layer: ToolLayer) -> None:
    """注册工具层级

    Args:
        tool_name: 工具名称
        layer: 工具层级
    """
    _TOOL_LAYERS[tool_name] = layer

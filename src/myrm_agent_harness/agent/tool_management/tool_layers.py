"""工具层级定义 - 缓存友好的工具排序基础

1. 本文件的 INPUT/OUTPUT/POS 注释
3. agent/context_management/PROMPT_CACHE_PRACTICE.md §2.1 工具分层排序

[INPUT]
(none — pure enum + dict, no external deps)

[OUTPUT]
- ToolLayer: 工具层级枚举(CORE=1, COMMON=2, EXTENDED=3, EXTERNAL=4)
- register_tool_layer(): 注册工具到指定层级
- get_tool_layer(): 获取工具的层级
- get_tool_registry_sort_key(): Cache-friendly sort key for ToolRegistry
- tool_layer_snapshot_label(): GUI-facing layer slug (core/common/extended/external)
- is_registered_action_tool(): 判断工具名是否在 Action Tool SSOT 中

[POS]
Tool layer priority registry. Defines CORE/COMMON/EXTENDED/EXTERNAL four-tier tool priorities used by ToolRegistry for ordering.

Tool loading dual-track (SSOT):
- General track (Web non-fast, Channel/IM, Cron/Kanban): CORE tools always Turn1 eager via tool_mount.resolve_agent_mount → get_meta_tools(enable_shell_tools=True).
- Search/Fast track: Web `action_mode=fast` only — no write/shell; UECD read-only `file_read_tool` via `FileAccessMode.SPILL_AND_UPLOADS` (server `tool_mount.resolve_agent_mount`).
- Channel/IM binds General agents only; prompt_mode=search agents rejected at bind API.

"""

from enum import IntEnum


class ToolLayer(IntEnum):
    """工具层级定义 - 数值越小越靠前

    设计目标:最大化 Prompt Cache 命中率

    层级说明:
    - CORE: 核心工具,始终存在,不可关闭
    - COMMON: 通用工具,默认存在,前端可控制开关
    - EXTENDED: harness 可选能力,按需 Turn1 加载
    - EXTERNAL: 框架外来源(server vendor / MCP direct / OpenAPI / 未登记动态工具)
    """

    CORE = 1
    COMMON = 2
    EXTENDED = 3
    EXTERNAL = 4


# 工具层级注册表
#
# 设计原则:
# 1. 始终加载的工具放 CORE,永远在最前面,缓存稳定
# 2. 默认开启但可关的工具放 COMMON,在中间
# 3. harness 可选工具放 EXTENDED
# 4. 框架外工具(server vendor / MCP / OpenAPI)放 EXTERNAL,永远在最后
#
# 排序规则:按层级排序; COMMON 层内 memory 组优先于 web_search，其余按名称字母序
# 缓存原理:Prompt Cache 是前缀匹配,CORE 工具放最前面可保证永远被缓存
#
# 工具名称必须与 @tool() 装饰器中声明的名称完全一致
#
# 架构边界:此处仅登记 harness 框架自有工具。业务层 vendor 集成 tool（如 x_search_tool）
# 在 myrm-agent-server `_tool_layer_bootstrap.py` 登记为 EXTERNAL; MCP/OpenAPI 运行时未登记名默认 EXTERNAL。
_TOOL_LAYERS: dict[str, ToolLayer] = {
    # ============================================================
    # CORE - 通用 Agent 基线工具（无条件 Turn1 eager，前端无开关）
    # General 轨道：Web 非 fast、Channel/IM、Cron/Kanban — server tool_mount.resolve_agent_mount
    # Search/Fast 无 file/bash：仅 Web action_mode=fast — 见 server params/converter.py
    # ============================================================
    "web_fetch_tool": ToolLayer.CORE,
    "bash_code_execute_tool": ToolLayer.CORE,
    "bash_process_tool": ToolLayer.CORE,
    "file_edit_tool": ToolLayer.CORE,
    "file_read_tool": ToolLayer.CORE,
    "file_write_tool": ToolLayer.CORE,
    "glob_tool": ToolLayer.CORE,
    "grep_tool": ToolLayer.CORE,
    # ============================================================
    # COMMON - 默认开启但用户可在 GUI 关闭（放中间；组内 memory 优先于 web_search）
    # ============================================================
    "web_search_tool": ToolLayer.COMMON,
    "memory_search_tool": ToolLayer.COMMON,
    "memory_save_tool": ToolLayer.COMMON,
    "memory_manage_tool": ToolLayer.COMMON,
    # ============================================================
    # EXTENDED - harness 可选能力(Turn1 按需); EXTERNAL 在其后, 见 get_tool_layer 默认 fallback
    # ============================================================
    # --- 代码结构与符号分析 ---
    "ast_symbol_search_tool": ToolLayer.EXTENDED,
    # --- ACP（Agent Communication Protocol）---
    "delegate_to_agent_tool": ToolLayer.EXTENDED,
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
    # --- Goal / planning 工具 ---
    "complete_goal_tool": ToolLayer.EXTENDED,
    "todo_write": ToolLayer.EXTENDED,
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
    "kanban_cancel_task": ToolLayer.EXTENDED,
    "kanban_retry_task": ToolLayer.EXTENDED,
    "kanban_revise_plan": ToolLayer.EXTENDED,
    # --- 记忆工具（search/save/manage → COMMON；sessions/wiki 通过 corpus ACL）---
    # --- 技能工具 ---
    "skill_search_tool": ToolLayer.EXTENDED,
    "skill_market_tool": ToolLayer.EXTENDED,
    "skill_manage_tool": ToolLayer.EXTENDED,
    "skill_select_tool": ToolLayer.EXTENDED,
    # --- Sub-Agent 管理 ---
    "delegate_task_tool": ToolLayer.EXTENDED,
    "subagent_control_tool": ToolLayer.EXTENDED,
    "send_teammate_message_tool": ToolLayer.EXTENDED,
    # --- Wiki 知识库 (Agent 面向仅 ingest / query / apply) ---
    "wiki_ingest_tool": ToolLayer.EXTENDED,
    "wiki_query_tool": ToolLayer.EXTENDED,
    "wiki_apply_tool": ToolLayer.EXTENDED,
    # --- PDF 模板导出工具 ---
    "list_pdf_templates": ToolLayer.EXTENDED,
    "get_pdf_template_schema": ToolLayer.EXTENDED,
    "render_pdf_template": ToolLayer.EXTENDED,
}


# COMMON 层组内排序：高频默认能力簇优先，单工具开关次之（组内仍按 name 稳定排序）
_COMMON_LAYER_SORT_RANK: dict[str, int] = {
    "memory_manage_tool": 0,
    "memory_search_tool": 1,
    "memory_save_tool": 2,
    "web_search_tool": 10,
}

# EXTENDED: skill cluster first so toggling other EXTENDED tools preserves skill prefix cache.
_EXTENDED_LAYER_SORT_RANK: dict[str, int] = {
    "skill_select_tool": 0,
    "skill_search_tool": 1,
    "skill_manage_tool": 2,
    "skill_market_tool": 3,
}


_LAYER_SNAPSHOT_LABELS: dict[ToolLayer, str] = {
    ToolLayer.CORE: "core",
    ToolLayer.COMMON: "common",
    ToolLayer.EXTENDED: "extended",
    ToolLayer.EXTERNAL: "external",
}


def tool_layer_snapshot_label(layer: ToolLayer) -> str:
    """Return a stable GUI-facing slug for a tool layer."""
    return _LAYER_SNAPSHOT_LABELS[layer]


def get_tool_registry_sort_key(
    tool_name: str, layer: ToolLayer
) -> tuple[int, int, str]:
    """Cache-friendly registry sort key: layer → group rank → name."""
    if layer == ToolLayer.COMMON:
        group_rank = _COMMON_LAYER_SORT_RANK.get(tool_name, 50)
        return (int(layer), group_rank, tool_name)
    if layer == ToolLayer.EXTENDED:
        group_rank = _EXTENDED_LAYER_SORT_RANK.get(tool_name, 50)
        return (int(layer), group_rank, tool_name)
    return (int(layer), 0, tool_name)


def get_tool_layer(tool_name: str) -> ToolLayer:
    """获取工具层级

    [核心架构约束]: 保护大模型 Prompt Prefix Cache
    harness SSOT 工具使用 CORE/COMMON/EXTENDED; 框架外工具(MCP direct / OpenAPI /
    server vendor / 一切未登记名)使用 EXTERNAL, 排序上永远位于 harness 三层之后.

    Args:
        tool_name: 工具名称

    Returns:
        工具层级; 未在 harness ``_TOOL_LAYERS`` 或 server bootstrap 登记的工具默认为 EXTERNAL
    """
    return _TOOL_LAYERS.get(tool_name, ToolLayer.EXTERNAL)


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

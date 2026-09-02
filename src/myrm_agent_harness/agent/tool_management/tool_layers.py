"""工具层级定义 - 缓存友好的工具排序基础

1. 本文件的 INPUT/OUTPUT/POS 注释
3. agent/context_management/PROMPT_CACHE_PRACTICE.md §2.1 工具分层排序

[INPUT]
(none — pure enum + dict, no external deps)

[OUTPUT]
- ToolLayer: 工具层级枚举(CORE=1, HIGH_PRIORITY=2, EXTENDED=3, EXTERNAL=4)
- get_tool_replay_safety(): 获取工具崩溃恢复回放安全性分类 (SAFE / NEVER)
- register_tool_layer(): 注册工具到指定层级
- get_tool_layer(): 获取工具的层级
- get_tool_registry_sort_key(): Cache-friendly sort key for ToolRegistry
- tool_layer_snapshot_label(): GUI-facing layer slug (core/high_priority/extended/external)
- is_registered_action_tool(): 判断工具名是否在 Action Tool SSOT 中

[POS]
Tool layer priority registry. Defines CORE/HIGH_PRIORITY/EXTENDED/EXTERNAL four-tier tool priorities used by ToolRegistry for ordering.

Tool loading dual-track (SSOT):
- General track (Web non-fast, Channel/IM, Cron/Kanban): CORE tools always Turn1 eager via tool_mount.resolve_agent_mount → get_meta_tools(enable_shell_tools=True).
- Search/Fast track: Web `action_mode=fast` only — no write/shell; UECD read-only `file_read_tool` via `FileAccessMode.SPILL_AND_UPLOADS` (server `tool_mount.resolve_agent_mount`).
- Channel/IM binds General agents only; prompt_mode=search agents rejected at bind API.

"""

from enum import IntEnum

from myrm_agent_harness.agent.tool_management.types import ReplaySafety


class ToolLayer(IntEnum):
    """工具层级定义 - 数值越小越靠前

    设计目标:最大化 Prompt Cache 命中率

    层级说明与架构定位:
    - CORE (Layer 1): 核心层基线工具，100% 始终存在，无前端开关，不可关闭（保证终极前缀缓存）
    - HIGH_PRIORITY (Layer 2): 高优层标配工具，默认全局开启/挂载（Default-ON），支持前端/配置按需关闭（User-Togglable，如搜索、记忆、技能选择）
    - EXTENDED (Layer 3): 扩展层可选高级能力，按需装配（Profile 开关或特定意图触发），默认关闭不全开
    - EXTERNAL (Layer 4): 外部业务层工具（非 harness 内置，server vendor / MCP direct / OpenAPI / 动态工具），永远位于末尾
    """

    CORE = 1
    HIGH_PRIORITY = 2
    EXTENDED = 3
    EXTERNAL = 4


# 工具层级注册表
#
# 设计原则:
# 1. 始终加载的工具放 CORE,永远在最前面,保证绝对前缀缓存稳定
# 2. 默认开启但支持用户关闭的标配工具放 HIGH_PRIORITY（Default-ON, User-Togglable）,在中间; 组内 web_search 优先置顶
# 3. harness 可选/重型能力工具放 EXTENDED
# 4. 框架外工具(server vendor / MCP / OpenAPI)放 EXTERNAL,永远在最后
#
# 排序规则:按层级排序; HIGH_PRIORITY 层内 web_search 优先于 memory 组，其余按名称字母序
# 缓存原理:Prompt Cache 是前缀匹配,CORE 工具放最前面可保证永远被缓存
#
# 工具名称必须与 @tool() 装饰器中声明的名称完全一致
#
# 架构边界:此处仅登记 harness 框架自有工具。业务层 vendor 集成 tool
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
    # HIGH_PRIORITY - 高优层：默认开启/挂载，支持前端/配置按需关闭（User-Togglable）
    # 组内严格排序：搜索工具 (Rank 0) -> 记忆工具 (Rank 10~12) -> 技能选择工具 (Rank 20)
    # ============================================================
    "web_search_tool": ToolLayer.HIGH_PRIORITY,
    "memory_search_tool": ToolLayer.HIGH_PRIORITY,
    "memory_save_tool": ToolLayer.HIGH_PRIORITY,
    "memory_manage_tool": ToolLayer.HIGH_PRIORITY,
    "skill_select_tool": ToolLayer.HIGH_PRIORITY,
    # ============================================================
    # EXTENDED - 扩展层：harness 可选高级能力(Turn1 按需); EXTERNAL 在其后, 见 get_tool_layer 默认 fallback
    # ============================================================
    # --- ACP（Agent Communication Protocol）---
    "invoke_acp_agent_tool": ToolLayer.EXTENDED,
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
    # --- 记忆工具（search/save/manage → HIGH_PRIORITY；sessions/wiki 通过 corpus ACL）---
    # --- 技能工具 ---
    "skill_search_tool": ToolLayer.EXTENDED,
    "skill_market_tool": ToolLayer.EXTENDED,
    "skill_manage_tool": ToolLayer.EXTENDED,
    # --- Sub-Agent 管理 ---
    "delegate_task_tool": ToolLayer.EXTENDED,
    "subagent_control_tool": ToolLayer.EXTENDED,
    "send_teammate_message_tool": ToolLayer.EXTENDED,
    # --- Wiki 知识库 (Agent 面向仅 ingest / query / apply) ---
    "wiki_ingest_tool": ToolLayer.EXTENDED,
    "wiki_query_tool": ToolLayer.EXTENDED,
    "wiki_apply_tool": ToolLayer.EXTENDED,
}


# HIGH_PRIORITY 层组内排序：web_search 优先置顶，记忆三件套紧随其后，技能选择工具承接（组内按 rank 稳定排序）
_HIGH_PRIORITY_LAYER_SORT_RANK: dict[str, int] = {
    "web_search_tool": 0,
    "memory_manage_tool": 10,
    "memory_search_tool": 11,
    "memory_save_tool": 12,
    "skill_select_tool": 20,
}


_LAYER_SNAPSHOT_LABELS: dict[ToolLayer, str] = {
    ToolLayer.CORE: "core",
    ToolLayer.HIGH_PRIORITY: "high_priority",
    ToolLayer.EXTENDED: "extended",
    ToolLayer.EXTERNAL: "external",
}


def tool_layer_snapshot_label(layer: ToolLayer) -> str:
    """Return a stable GUI-facing slug for a tool layer."""
    return _LAYER_SNAPSHOT_LABELS[layer]


def get_tool_registry_sort_key(
    tool_name: str, layer: ToolLayer
) -> tuple[int, int, str]:
    """Cache-friendly registry sort key: layer → group rank → name.

    高优层按 _HIGH_PRIORITY_LAYER_SORT_RANK 排序以固化高优 Golden Prefix;
    CORE、EXTENDED、EXTERNAL 层统一按字母序 (group_rank=0) 稳定排序.
    """
    if layer == ToolLayer.HIGH_PRIORITY:
        group_rank = _HIGH_PRIORITY_LAYER_SORT_RANK.get(tool_name, 50)
        return (int(layer), group_rank, tool_name)
    return (int(layer), 0, tool_name)


def get_tool_layer(tool_name: str) -> ToolLayer:
    """获取工具层级

    [核心架构约束]: 保护大模型 Prompt Prefix Cache
    harness SSOT 工具使用 CORE/HIGH_PRIORITY/EXTENDED; 框架外工具(MCP direct / OpenAPI /
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


# ============================================================
# ReplaySafety SSOT 注册表
# SAFE: 幂等/纯只读工具，崩溃恢复时允许透明安全重放补全结果
# 默认/未声明: ReplaySafety.NEVER（安全第一原则）
# ============================================================
_TOOL_REPLAY_SAFETY: dict[str, ReplaySafety] = {
    # 只读文件与搜索工具
    "file_read_tool": ReplaySafety.SAFE,
    "grep_tool": ReplaySafety.SAFE,
    "glob_tool": ReplaySafety.SAFE,
    "web_search_tool": ReplaySafety.SAFE,
    "web_fetch_tool": ReplaySafety.SAFE,
    "memory_search_tool": ReplaySafety.SAFE,
    "wiki_query_tool": ReplaySafety.SAFE,
    "skill_search_tool": ReplaySafety.SAFE,
    "browser_inspect_tool": ReplaySafety.SAFE,
    "browser_snapshot_tool": ReplaySafety.SAFE,
    "desktop_snapshot_tool": ReplaySafety.SAFE,
    "desktop_vision_tool": ReplaySafety.SAFE,
    "kanban_show": ReplaySafety.SAFE,
    "kanban_list_tasks": ReplaySafety.SAFE,
}


def get_tool_replay_safety(tool_name: str) -> ReplaySafety:
    """获取工具的重放安全等级（未登记工具一律默认为 NEVER）"""
    return _TOOL_REPLAY_SAFETY.get(tool_name, ReplaySafety.NEVER)


def register_tool_layer(tool_name: str, layer: ToolLayer) -> None:
    """注册工具层级

    Args:
        tool_name: 工具名称
        layer: 工具层级
    """
    _TOOL_LAYERS[tool_name] = layer

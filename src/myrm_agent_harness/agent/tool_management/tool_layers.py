"""工具层级定义 - 缓存友好的工具排序基础

1. 本文件的 INPUT/OUTPUT/POS 注释
3. agent/context_management/PROMPT_CACHE_PRACTICE.md §2.1 工具分层排序

[INPUT]
(none — pure enum + dict, no external deps)

[OUTPUT]
- ToolLayer: 工具层级枚举(CORE=1, COMMON=2, EXTENDED=3)
- register_tool_layer(): 注册工具到指定层级
- get_tool_layer(): 获取工具的层级

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
# 注意:researcher_tool 不在这里,它专属于深度搜索智能体
#
# 设计原则:
# 1. 始终加载的工具放 CORE,永远在最前面,缓存稳定
# 2. 默认开启但可关的工具放 COMMON,在中间
# 3. 按需加载的工具放 EXTENDED,在最后,变化只影响自己
#
# 排序规则:按层级排序,同层级内按名称字母序
# 缓存原理:Prompt Cache 是前缀匹配,CORE 工具放最前面可保证永远被缓存
#
# 工具名称必须与 @tool() 装饰器中声明的名称完全一致
#
# 架构边界:此处登记 harness 框架自有工具。业务层 vendor 集成 tool（如 x_search_tool）
# 在 myrm-agent-server 通过 skill-gated deferred 注册,以维持框架-业务层分离原则。
_TOOL_LAYERS: dict[str, ToolLayer] = {
    # ============================================================
    # CORE - 始终加载且不可关闭(放最前面,永远缓存)
    # 仅包含真正无条件存在、不受用户配置影响的工具
    # ============================================================
    "web_fetch_tool": ToolLayer.CORE,
    # ============================================================
    # COMMON - 默认开启但受用户配置控制(放中间)
    # 大多数场景启用,用户可通过 GUI enabled_builtin_tools 开关控制
    # ============================================================
    "request_answer_user_tool": ToolLayer.COMMON,
    "bash_code_execute_tool": ToolLayer.COMMON,
    # Background-process companions of bash_code_execute_tool. Opt-in (only
    # appear when enable_bash=True), so EXTENDED keeps them out of the always-
    # on prefix cache slot.
    "bash_process_list_tool": ToolLayer.EXTENDED,
    "bash_process_output_tool": ToolLayer.EXTENDED,
    "bash_process_kill_tool": ToolLayer.EXTENDED,
    "file_edit_tool": ToolLayer.COMMON,
    "file_read_tool": ToolLayer.COMMON,
    "file_write_tool": ToolLayer.COMMON,
    "planner_tool": ToolLayer.COMMON,
    "web_search_tool": ToolLayer.COMMON,
    # ============================================================
    # EXTENDED - 按需加载或低频辅助工具(放最后,变化不影响前面的缓存)
    # ============================================================
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
    "desktop_inspect_tool": ToolLayer.EXTENDED,
    "desktop_snapshot_tool": ToolLayer.EXTENDED,
    "desktop_interact_tool": ToolLayer.EXTENDED,
    "desktop_vision_tool": ToolLayer.EXTENDED,
    # --- 渠道通知 ---
    "channel_notify_tool": ToolLayer.EXTENDED,
    # --- Cron 定时任务 ---
    "cron_manage_tool": ToolLayer.EXTENDED,
    # --- Deploy ---
    "deploy_artifact": ToolLayer.EXTENDED,
    # --- 文件搜索 ---
    "glob_tool": ToolLayer.EXTENDED,
    "grep_tool": ToolLayer.EXTENDED,
    # --- Goal 工具 ---
    "get_goal_status_tool": ToolLayer.EXTENDED,
    "update_goal_status_tool": ToolLayer.EXTENDED,
    # --- 批量 LLM (fan-out) ---
    "llm_map_tool": ToolLayer.EXTENDED,
    # --- 交互工具 ---
    "ask_question_tool": ToolLayer.EXTENDED,
    "tts_generate": ToolLayer.EXTENDED,
    "image_tool": ToolLayer.EXTENDED,
    "video_tool": ToolLayer.EXTENDED,
    "render_ui_tool": ToolLayer.EXTENDED,
    # --- 看板 (Worker tools) ---
    "kanban_show": ToolLayer.EXTENDED,
    "kanban_complete": ToolLayer.EXTENDED,
    "kanban_block": ToolLayer.EXTENDED,
    "kanban_heartbeat": ToolLayer.EXTENDED,
    "kanban_comment": ToolLayer.EXTENDED,
    # --- 看板 (Orchestrator tools) ---
    "kanban_add_task": ToolLayer.EXTENDED,
    "kanban_list_tasks": ToolLayer.EXTENDED,
    "kanban_update_task": ToolLayer.EXTENDED,
    "kanban_move_task": ToolLayer.EXTENDED,
    "kanban_delete_task": ToolLayer.EXTENDED,
    "kanban_board_summary": ToolLayer.EXTENDED,
    "kanban_add_dependency": ToolLayer.EXTENDED,
    "kanban_remove_dependency": ToolLayer.EXTENDED,
    # --- 看板 (Management tools) ---
    "kanban_create_board": ToolLayer.EXTENDED,
    "kanban_list_boards": ToolLayer.EXTENDED,
    "kanban_get_task": ToolLayer.EXTENDED,
    # --- 记忆工具 ---
    "conversation_search_tool": ToolLayer.EXTENDED,
    "memory_manage_tool": ToolLayer.EXTENDED,
    "memory_recall_tool": ToolLayer.EXTENDED,
    "memory_save_tool": ToolLayer.EXTENDED,
    # --- 运行时诊断 ---
    "runtime_diagnostics_tool": ToolLayer.EXTENDED,
    # --- 技能工具 ---
    "discover_capability_tool": ToolLayer.EXTENDED,
    "skill_analyze_tool": ToolLayer.EXTENDED,
    "skill_discovery_tool": ToolLayer.EXTENDED,
    "skill_manage_tool": ToolLayer.EXTENDED,
    "skill_select_tool": ToolLayer.EXTENDED,
    # --- Sub-Agent 管理 ---
    "batch_delegate_tasks_tool": ToolLayer.EXTENDED,
    "cancel_subagent_tool": ToolLayer.EXTENDED,
    "delegate_parallel_tasks_tool": ToolLayer.EXTENDED,
    "delegate_task_tool": ToolLayer.EXTENDED,
    "spawn_subagent": ToolLayer.EXTENDED,
    "notify": ToolLayer.EXTENDED,
    "list_subagents_tool": ToolLayer.EXTENDED,
    "send_teammate_message_tool": ToolLayer.EXTENDED,
    "steer_subagent_tool": ToolLayer.EXTENDED,
    # --- Vault 工具 ---
    "vault_extract_tool": ToolLayer.EXTENDED,
    "vault_get_tool": ToolLayer.EXTENDED,
    "vault_put_tool": ToolLayer.EXTENDED,
    # --- Wiki 知识库 ---
    "wiki_compile_tool": ToolLayer.EXTENDED,
    "wiki_ingest_tool": ToolLayer.EXTENDED,
    "wiki_maintain_tool": ToolLayer.EXTENDED,
    "wiki_query_tool": ToolLayer.EXTENDED,
    # --- Deep Research 编排器内部工具（伪工具，仅作为 JSON schema 注入 LLM，
    #     编排器截获 tool_call 驱动状态机转换，不经过运行时执行）---
    "dispatch_research": ToolLayer.EXTENDED,
    "finalize_report": ToolLayer.EXTENDED,
    "think": ToolLayer.EXTENDED,
    # --- 编排器验证子Agent内部工具 ---
    "submit_verdict": ToolLayer.EXTENDED,
    # --- 框架内部工具（deferred, 不暴露给 LLM）---
    "_completion_check": ToolLayer.EXTENDED,
}


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


def register_tool_layer(tool_name: str, layer: ToolLayer) -> None:
    """注册工具层级

    Args:
        tool_name: 工具名称
        layer: 工具层级
    """
    _TOOL_LAYERS[tool_name] = layer

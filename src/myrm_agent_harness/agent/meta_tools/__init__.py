"""Agent meta-tools module — tools depending on Agent framework infrastructure.

[INPUT]
- bash::create_bash_code_execute_tool (POS: Bash 代码执行工具创建函数)
- file_ops::create_file_read_tool, create_file_write_tool, create_file_edit_tool (POS: 文件操作工具创建函数)
- file_search::create_glob_tool, create_grep_tool (POS: 文件搜索工具创建函数)
- skills.select::create_select_skill_tool (POS: 技能选择工具创建函数)
- discover_capability::sync_discover_capability_tool (POS: 统一能力发现网关，由 SkillAgent 调用)
- skills.market::create_skill_market_tool (POS: 外部技能市场工具创建函数)
- skills.manage::create_skill_manage_tool (POS: 技能管理工具创建函数)
- spawn_subagent::create_delegate_task_tool, create_subagent_control_tool (POS: Subagent 委派与控制 LLM 工具)
[OUTPUT]
- get_meta_tools: 获取所有元工具的函数(含自适应技能搜索逻辑)
- 各个工具的 create_xxx_tool 工厂函数
- SKILL_INLINE_THRESHOLD, SKILL_CORE_MAX: 自适应阈值常量（定义于 agent.skills.runtime.catalog_display）

[POS]
Agent meta-tools module. Provides tools that depend on Agent framework infrastructure:
Bash, File Ops, File Search, and Skill system.

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.agent.meta_tools.mount_policy import FileAccessMode

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
    from myrm_agent_harness.backends.skills.protocols import SkillBackend
    from myrm_agent_harness.backends.skills.types import SkillInstance, SkillMetadata
    from myrm_agent_harness.toolkits.memory.protocols.cache import (
        EmbeddingCacheProtocol,
    )
    from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig

# Agent 专属工具(本模块)
from myrm_agent_harness.agent.skills.runtime.catalog_display import (
    SKILL_CORE_MAX,
    SKILL_INLINE_THRESHOLD,
    SKILL_SELECT_INLINE_MAX,
    resolve_catalog_display_skills,
)

from .answer_user_tool import request_answer_user_tool
from .bash import create_bash_code_execute_tool, create_bash_process_tool
from .file_ops import (
    create_file_edit_tool,
    create_file_read_tool,
    create_file_write_tool,
)
from .file_search import create_glob_tool, create_grep_tool
from .skills.manage import create_skill_manage_tool
from .skills.market import create_skill_market_tool
from .skills.select import create_select_skill_tool
from .spawn_subagent import (
    create_delegate_task_tool,
    create_subagent_control_tool,
)


def get_meta_tools(
    skills: list[SkillMetadata],
    skill_backend: SkillBackend | None = None,
    embedding_config: EmbeddingConfig | None = None,
    embedding_cache: EmbeddingCacheProtocol | None = None,
    skill_env_map: dict[str, dict[str, str]] | None = None,
    skill_configs: dict[str, dict[str, object]] | None = None,
    global_env: dict[str, str] | None = None,
    registry: ToolRegistry | None = None,
    file_access_mode: FileAccessMode = FileAccessMode.FULL,
    enable_shell_tools: bool = True,
    enable_answer_tool: bool = False,
    has_manage_tool: bool = False,
    available_tool_names: frozenset[str] | None = None,
    available_tool_groups: frozenset[str] | None = None,
    skill_instances: dict[str, SkillInstance] | None = None,
) -> list[BaseTool]:
    """获取元工具列表

    返回所有元工具,用于在 create_agent 时传入 tools 参数.

    **双层技能注入策略**:
    - 若提供 `skill_configs`:严格遵循配置中的 `is_core` 标志.
      `is_core=True` 的技能内联注入,其余作为外围技能放入搜索工具.
    - 若未提供 `skill_configs` (向下兼容):根据技能自身的 `always` 属性和内置阈值进行自适应截断.
    - available=False 的技能不内联(不浪费名额)

    **搜索模式**:
    - 无 embedding_config (默认): BM25 词法 + Prompt 引导多语言
    - 有 embedding_config: Hybrid 混合搜索(BM25+Embedding+RRF), 词法+语义双保障

    Skill tools extract user_id at runtime from RunnableConfig context
    (consistent with bash_code_execute_tool's session_id pattern).

    Args:
        skills: 可用的技能列表
        skill_backend: 技能后端(用于 skill_select_tool)
        registry: ToolRegistry（必填；skill_search_tool 由 SkillAgent 末尾 sync 注册）
        has_manage_tool: skill_manage_tool 是否 Turn1 挂载（由 server user_tools 或 SkillAgent 后端注入）
        embedding_config: Embedding 配置(可选, 用于语义搜索)
        embedding_cache: Embedding 缓存实例(可选, 仅 Hybrid 模式使用)
        skill_env_map: Per-skill resolved env vars (skill_name -> env dict).
        skill_configs: Per-agent skill configurations (e.g., is_core).
        skill_instances: Per-skill resolved SkillInstance objects (skill_name -> instance).
    Returns:
        元工具列表(根据技能情况动态组合)
    """
    import logging

    from myrm_agent_harness.backends.skills.types import skill_visible_for_tools

    logger = logging.getLogger(__name__)

    resolved_file_access = file_access_mode

    if registry is None:
        raise TypeError(
            "get_meta_tools requires a ToolRegistry instance; discoverable tools and "
            "skill_search_tool register exclusively via registry."
        )

    # --- Conditional skill filtering based on agent's tool capabilities ---
    if skills and (
        available_tool_names is not None or available_tool_groups is not None
    ):
        _atn = available_tool_names or frozenset()
        _atg = available_tool_groups or frozenset()
        pre_count = len(skills)
        visible: list[SkillMetadata] = []
        hidden_names: list[str] = []
        for s in skills:
            if skill_visible_for_tools(s, _atn, _atg):
                visible.append(s)
            else:
                hidden_names.append(s.name)
        if hidden_names:
            logger.info(
                " Tool-based skill filtering: %d/%d skills hidden (tool_names=%d, tool_groups=%d)",
                len(hidden_names),
                pre_count,
                len(_atn),
                len(_atg),
            )
            logger.debug(" Hidden skills: %s", hidden_names)
        skills = visible

    tools = []

    if skills and skill_backend is not None:
        catalog_resolution = resolve_catalog_display_skills(
            skills,
            skill_configs=skill_configs,
            available_tool_names=available_tool_names,
            available_tool_groups=available_tool_groups,
        )
        inline_skills = catalog_resolution.display_skills
        hidden_count = catalog_resolution.hidden_skill_count
        skill_select_tool = create_select_skill_tool(
            catalog_resolution.filtered_skills,
            skill_backend,
            skill_instances=skill_instances,
        )
        tools.append(skill_select_tool)
        if skill_configs is not None:
            logger.info(
                " Per-Agent 认知负载控制已启用: %d 个内联 (Core) + %d 个隐藏 (Peripheral)",
                len(inline_skills),
                hidden_count,
            )
        elif hidden_count > 0:
            logger.info(
                " skill_select_tool 已加载(%d 个模型可见技能内联, %d 个走 search)",
                len(inline_skills),
                hidden_count,
            )
        else:
            logger.info(
                " skill_select_tool 已加载(%d 个模型可见技能内联)",
                len(inline_skills),
            )
    else:
        if not skills:
            logger.info(" skill_select_tool 未加载(无可用技能)")
        else:
            logger.info(" skill_select_tool 未加载(skill_backend 未提供)")

    if enable_answer_tool:
        tools.append(request_answer_user_tool)
        logger.info(" request_answer_user_tool 已加载")
    else:
        logger.info(" request_answer_user_tool 已跳过 (enable_answer_tool=False)")

    if resolved_file_access == FileAccessMode.FULL:
        file_read_tool = create_file_read_tool(skills=skills)
        file_write_tool = create_file_write_tool(skills=skills)
        file_edit_tool = create_file_edit_tool(skills=skills)
        glob_tool = create_glob_tool()
        grep_tool = create_grep_tool()
        tools.extend(
            [file_read_tool, file_write_tool, file_edit_tool, glob_tool, grep_tool]
        )
    elif resolved_file_access == FileAccessMode.SPILL_AND_UPLOADS:
        file_read_tool = create_file_read_tool(
            skills=skills, path_policy="evicted_uploaded"
        )
        tools.append(file_read_tool)
        logger.info(
            " UECD read-only file_read_tool mounted (evicted + uploaded paths only)"
        )
    else:
        logger.info("File tools disabled by caller configuration")

    if enable_shell_tools:
        bash_code_execute = create_bash_code_execute_tool(
            skills=skills,
            skill_env_map=skill_env_map,
            global_env=global_env,
        )
        tools.append(bash_code_execute)
        tools.append(create_bash_process_tool())
    else:
        logger.info("Bash tool disabled by caller configuration")

    # discover_capability_tool → skill_search_tool SSOT: SkillAgent calls sync_discover_capability_tool()
    # after all skills are registered.
    discoverable_skills = [s for s in skills if s.model_invocable] if skills else []
    if discoverable_skills:
        logger.info(
            " skill_search_tool deferred to sync_discover_capability_tool "
            "(可搜索技能: %d)",
            len(discoverable_skills),
        )
    else:
        logger.info(" skill_search_tool 未加载(无可搜索技能)")

    return tools


__all__ = [
    "SKILL_CORE_MAX",
    "SKILL_INLINE_THRESHOLD",
    "SKILL_SELECT_INLINE_MAX",
    "FileAccessMode",
    "create_bash_code_execute_tool",
    "create_bash_process_tool",
    "create_delegate_task_tool",
    "create_file_edit_tool",
    "create_file_read_tool",
    "create_file_write_tool",
    "create_glob_tool",
    "create_grep_tool",
    "create_select_skill_tool",
    "create_skill_manage_tool",
    "create_skill_market_tool",
    "create_subagent_control_tool",
    "get_meta_tools",
    "request_answer_user_tool",
]

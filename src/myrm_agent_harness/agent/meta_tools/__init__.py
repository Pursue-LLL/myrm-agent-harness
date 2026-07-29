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
- SKILL_INLINE_THRESHOLD, SKILL_CORE_MAX: 自适应阈值常量

[POS]
Agent meta-tools module. Provides tools that depend on Agent framework infrastructure:
Bash, File Ops, File Search, and Skill system.

"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
    from myrm_agent_harness.backends.skills.market_protocols import (
        SkillMarketBackend,
    )
    from myrm_agent_harness.backends.skills.protocols import SkillBackend
    from myrm_agent_harness.backends.skills.scanning_write_backend import (
        ScanningSkillWriteBackend,
    )
    from myrm_agent_harness.backends.skills.similarity import SkillSimilarityChecker
    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.memory.protocols.cache import (
        EmbeddingCacheProtocol,
    )
    from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig

# Agent 专属工具(本模块)
from .answer_user_tool import request_answer_user_tool
from .bash import create_bash_code_execute_tool, create_bash_process_tool
from .file_ops import (
    create_file_edit_tool,
    create_file_read_tool,
    create_file_write_tool,
)
from .file_search import create_glob_tool, create_grep_tool
from .skills.market import create_skill_market_tool
from .skills.manage import create_skill_manage_tool
from .skills.select import create_select_skill_tool
from .spawn_subagent import (
    create_delegate_task_tool,
    create_subagent_control_tool,
)

SKILL_INLINE_THRESHOLD = 20
SKILL_CORE_MAX = 10
SKILL_SELECT_INLINE_MAX = 20


def get_meta_tools(
    skills: list[SkillMetadata],
    skill_backend: SkillBackend | None = None,
    embedding_config: EmbeddingConfig | None = None,
    embedding_cache: EmbeddingCacheProtocol | None = None,
    skill_env_map: dict[str, dict[str, str]] | None = None,
    skill_configs: dict[str, dict[str, object]] | None = None,
    global_env: dict[str, str] | None = None,
    registry: ToolRegistry | None = None,
    enable_file_tools: bool = True,
    enable_evicted_read: bool = False,
    enable_shell_tools: bool = True,
    enable_answer_tool: bool = False,
    has_manage_tool: bool = False,
    available_tool_names: frozenset[str] | None = None,
    available_tool_groups: frozenset[str] | None = None,
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
    Returns:
        元工具列表(根据技能情况动态组合)
    """
    import logging

    from myrm_agent_harness.backends.skills.types import skill_visible_for_tools

    logger = logging.getLogger(__name__)

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

    def _sorted_inline(skills_to_inline: list[SkillMetadata]) -> list[SkillMetadata]:
        return sorted(skills_to_inline, key=lambda skill: skill.name)[
            :SKILL_SELECT_INLINE_MAX
        ]

    if skills and skill_backend is not None:
        available_skills = [s for s in skills if s.available]
        model_visible_skills = [s for s in available_skills if s.model_invocable]

        if skill_configs is not None:
            core_candidates = [
                s
                for s in model_visible_skills
                if skill_configs.get(s.id, {}).get("is_core", False)
            ]
            inline_skills = _sorted_inline(core_candidates)
            hidden_count = len(model_visible_skills) - len(inline_skills)
            skill_select_tool = create_select_skill_tool(
                skills,
                skill_backend,
                inline_skills=inline_skills,
                hidden_skill_count=hidden_count,
                has_manage_tool=has_manage_tool,
            )
            tools.append(skill_select_tool)
            logger.info(
                " Per-Agent 认知负载控制已启用: %d 个内联 (Core) + %d 个隐藏 (Peripheral)",
                len(inline_skills),
                hidden_count,
            )
        else:
            always_skills = sorted(
                [s for s in model_visible_skills if s.always], key=lambda skill: skill.name
            )
            non_always_skills = sorted(
                [s for s in model_visible_skills if not s.always],
                key=lambda skill: skill.name,
            )

            if len(model_visible_skills) > SKILL_INLINE_THRESHOLD:
                remaining = max(SKILL_SELECT_INLINE_MAX - len(always_skills), 0)
                core_non_always = non_always_skills[: min(SKILL_CORE_MAX, remaining)]
                inline_skills = _sorted_inline(always_skills + core_non_always)
                hidden_count = len(model_visible_skills) - len(inline_skills)
                skill_select_tool = create_select_skill_tool(
                    skills,
                    skill_backend,
                    inline_skills=inline_skills,
                    hidden_skill_count=hidden_count,
                    has_manage_tool=has_manage_tool,
                )
                tools.append(skill_select_tool)
                logger.info(
                    " 自适应技能选择已启用: %d 个内联(%d always + %d core) + %d 个隐藏",
                    len(inline_skills),
                    len(always_skills),
                    len(core_non_always),
                    hidden_count,
                )
            else:
                inline_skills = _sorted_inline(model_visible_skills)
                hidden_count = len(model_visible_skills) - len(inline_skills)
                skill_select_tool = create_select_skill_tool(
                    skills,
                    skill_backend,
                    inline_skills=inline_skills,
                    hidden_skill_count=hidden_count,
                    has_manage_tool=has_manage_tool,
                )
                tools.append(skill_select_tool)
                logger.info(
                    " skill_select_tool 已加载(%d 个模型可见技能内联, %d 个走 search)",
                    len(inline_skills),
                    hidden_count,
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

    if enable_file_tools:
        file_read_tool = create_file_read_tool(skills=skills)
        file_write_tool = create_file_write_tool(skills=skills)
        file_edit_tool = create_file_edit_tool(skills=skills)
        glob_tool = create_glob_tool()
        grep_tool = create_grep_tool()
        tools.extend(
            [file_read_tool, file_write_tool, file_edit_tool, glob_tool, grep_tool]
        )
    elif enable_evicted_read:
        file_read_tool = create_file_read_tool(
            skills=skills, path_policy="evicted_uploaded"
        )
        tools.append(file_read_tool)
        logger.info(
            " UECD read-only file_read_tool mounted (evicted + uploaded paths only)"
        )
    else:
        logger.info("File tools disabled by caller configuration")

    # Mutable container: filled after all tools are built so that
    # bash Python PTC can access the full tool list via closure.
    _ptc_tools_ref: list = []

    if enable_shell_tools:
        bash_code_execute = create_bash_code_execute_tool(
            skills=skills,
            skill_env_map=skill_env_map,
            global_env=global_env,
            ptc_tools=_ptc_tools_ref,
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

    # PTC tools for bash Python execution — fill the mutable ref so that
    # BashExecutor.ptc_tools is populated before any actual execution.
    _ptc_tools_ref.extend(
        t
        for t in tools
        if t.name not in ("bash_code_execute_tool", "request_answer_user_tool")
    )
    logger.info(
        " PTC tools injected into bash_code_execute_tool (%d tools exposed via myrm_tools)",
        len(_ptc_tools_ref),
    )

    return tools


__all__ = [
    "SKILL_CORE_MAX",
    "SKILL_INLINE_THRESHOLD",
    "SKILL_SELECT_INLINE_MAX",
    "create_bash_code_execute_tool",
    "create_bash_process_tool",
    "create_delegate_task_tool",
    "create_subagent_control_tool",
    "create_file_edit_tool",
    "create_file_read_tool",
    "create_file_write_tool",
    "create_glob_tool",
    "create_grep_tool",
    "create_select_skill_tool",
    "create_skill_market_tool",
    "create_skill_manage_tool",
    "get_meta_tools",
    "request_answer_user_tool",
]

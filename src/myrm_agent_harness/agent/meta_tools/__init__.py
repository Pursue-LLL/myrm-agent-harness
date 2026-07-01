"""Agent meta-tools module — tools depending on Agent framework infrastructure.

[INPUT]
- bash::create_bash_tool (POS: Bash 代码执行工具创建函数)
- file_ops::create_file_read_tool, create_file_write_tool, create_file_edit_tool (POS: 文件操作工具创建函数)
- file_search::create_glob_tool, create_grep_tool (POS: 文件搜索工具创建函数)
- skills.select::create_select_skill_tool (POS: 技能选择工具创建函数)
- discover_capability::create_discover_capability_tool (POS: 统一能力发现网关)
- skills.discovery::create_skill_discovery_tool (POS: 外部技能发现工具创建函数)
- skills.manage::create_skill_manage_tool (POS: 技能管理工具创建函数)
- spawn_subagent::create_delegate_task_tool (POS: Subagent 委托工具创建函数)
- spawn_subagent::create_list_subagents_tool, create_cancel_subagent_tool,
  create_steer_subagent_tool (POS: Subagent 管理工具)
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
    from myrm_agent_harness.backends.skills.discovery_protocols import (
        SkillDiscoveryBackend,
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
from .bash import (
    create_bash_process_kill_tool,
    create_bash_process_list_tool,
    create_bash_process_output_tool,
    create_bash_tool,
)
from .discover_capability.discover_capability_tool import (
    create_discover_capability_tool,
)
from .file_ops import (
    create_file_edit_tool,
    create_file_read_tool,
    create_file_write_tool,
)
from .file_search import create_glob_tool, create_grep_tool
from .skills.analyze import create_skill_analyze_tool
from .skills.discovery import create_skill_discovery_tool
from .skills.manage import create_skill_manage_tool
from .skills.select import create_select_skill_tool
from .spawn_subagent import (
    create_batch_delegate_tasks_tool,
    create_cancel_subagent_tool,
    create_delegate_task_tool,
    create_list_subagents_tool,
    create_steer_subagent_tool,
)


SKILL_INLINE_THRESHOLD = 15
SKILL_CORE_MAX = 10


def get_meta_tools(
    skills: list[SkillMetadata],
    skill_backend: SkillBackend | None = None,
    discovery_backend: SkillDiscoveryBackend | None = None,
    write_backend: ScanningSkillWriteBackend | None = None,
    embedding_config: EmbeddingConfig | None = None,
    embedding_cache: EmbeddingCacheProtocol | None = None,
    skill_env_map: dict[str, dict[str, str]] | None = None,
    skill_configs: dict[str, dict[str, object]] | None = None,
    global_env: dict[str, str] | None = None,
    similarity_checker: SkillSimilarityChecker | None = None,
    registry: ToolRegistry | None = None,
    enable_file_tools: bool = True,
    enable_bash: bool = True,
    enable_answer_tool: bool = True,
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
    (consistent with bash_tool's session_id pattern).

    Args:
        skills: 可用的技能列表
        skill_backend: 技能后端(用于 skill_select_tool)
        discovery_backend: 技能发现后端(用于 skill_discovery_tool)
        write_backend: 技能写入后端(用于 skill_manage_tool, ScanningSkillWriteBackend)
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

    # --- Conditional skill filtering based on agent's tool capabilities ---
    if skills and (available_tool_names is not None or available_tool_groups is not None):
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
    has_manage_tool = write_backend is not None

    if skills and skill_backend is not None:
        available_skills = [s for s in skills if s.available]
        model_visible_skills = [s for s in available_skills if s.model_invocable]

        if skill_configs is not None:
            # Per-agent cognitive control (User-defined Core vs Peripheral)
            inline_skills = []
            for s in model_visible_skills:
                cfg = skill_configs.get(s.id, {})
                if cfg.get("is_core", False):
                    inline_skills.append(s)

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
            # Fallback to legacy hardcoded logic
            always_skills = [s for s in model_visible_skills if s.always]
            non_always_skills = [s for s in model_visible_skills if not s.always]

            if len(model_visible_skills) > SKILL_INLINE_THRESHOLD:
                core_non_always = non_always_skills[:SKILL_CORE_MAX]
                inline_skills = always_skills + core_non_always
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
                skill_select_tool = create_select_skill_tool(skills, skill_backend, has_manage_tool=has_manage_tool)
                tools.append(skill_select_tool)
                logger.info(f" skill_select_tool 已加载({len(model_visible_skills)} 个模型可见技能全部内联)")
    else:
        if not skills:
            logger.info(" skill_select_tool 未加载(无可用技能)")
        else:
            logger.info(" skill_select_tool 未加载(skill_backend 未提供)")

    if discovery_backend is not None:
        install_url_fn = getattr(discovery_backend, "install_from_url", None)
        uninstall_fn = getattr(discovery_backend, "uninstall", None)
        skill_disc_tool = create_skill_discovery_tool(
            discovery_backend,
            install_from_url_fn=install_url_fn,
            uninstall_fn=uninstall_fn,
        )
        tools.append(skill_disc_tool)
        logger.info("skill_discovery_tool loaded")

    if has_manage_tool:
        assert write_backend is not None  # narrowed by has_manage_tool
        skill_mgmt_tool = create_skill_manage_tool(write_backend, skill_backend, similarity_checker)
        tools.append(skill_mgmt_tool)
        logger.info(" skill_manage_tool 已加载")

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
        tools.extend([
            file_read_tool,
            file_write_tool,
            file_edit_tool,
            glob_tool,
            grep_tool
        ])
    else:
        logger.info("File tools disabled by caller configuration")

    # Low-frequency utility tools → deferred via registry (discoverable
    # through discover_capability_tool, auto-mounted on first use).
    _deferred_tools: list = []

    # Mutable container: filled after all tools are built so that
    # bash Python PTC can access the full tool list via closure.
    _ptc_tools_ref: list = []

    if enable_bash:
        bash_tool = create_bash_tool(
            skills=skills,
            skill_env_map=skill_env_map,
            global_env=global_env,
            ptc_tools=_ptc_tools_ref,
        )
        tools.append(bash_tool)
        _deferred_tools.extend(
            [
                create_bash_process_list_tool(),
                create_bash_process_output_tool(),
                create_bash_process_kill_tool(),
            ]
        )
    else:
        logger.info("Bash tool disabled by caller configuration")

    # Skill quality analysis: deferred (Curator/WebUI is primary cleanup path).
    # Mount via discover_capability when the user asks in chat.
    if skills:
        skills_snapshot = list(skills)
        _deferred_tools.append(
            create_skill_analyze_tool(get_all_skills_fn=lambda: skills_snapshot)
        )
        logger.info(" skill_analyze_tool registered as deferred")

    if registry is not None:
        from myrm_agent_harness.agent.tool_management.types import ToolSource

        for dt in _deferred_tools:
            registry.register(dt, source=ToolSource.META, deferred=True)
        logger.info(
            " %d 个低频工具已注册为 deferred: %s",
            len(_deferred_tools),
            [t.name for t in _deferred_tools],
        )
    else:
        tools.extend(_deferred_tools)
        logger.info(
            " %d 个低频工具直接加载 (无 registry): %s",
            len(_deferred_tools),
            [t.name for t in _deferred_tools],
        )

    # 统一能力发现网关：在 deferred 工具注册之后创建，确保
    # native_tool_map 包含所有已注册的 deferred 工具。
    discoverable_skills = [s for s in skills if s.model_invocable] if skills else []
    has_deferred = registry is not None and bool(registry.get_deferred_tools())
    if discoverable_skills or has_deferred:
        discover_capability_tool = create_discover_capability_tool(
            registry=registry,
            skills=discoverable_skills or None,
            embedding_config=embedding_config,
            cache=embedding_cache,
        )
        tools.append(discover_capability_tool)
        search_mode = "混合(BM25+Embedding+RRF)" if embedding_config is not None else "BM25"
        cache_status = "+缓存" if embedding_cache is not None and embedding_config is not None else ""
        logger.info(
            " 统一能力发现网关 discover_capability 已加载 (外部技能搜索模式: %s%s, deferred工具: %d)",
            search_mode,
            cache_status,
            len(registry.get_deferred_tools()) if registry else 0,
        )
    else:
        logger.info(" discover_capability_tool 未加载(无可搜索技能且无deferred工具)")

    # PTC tools for bash Python execution — fill the mutable ref so that
    # BashExecutor.ptc_tools is populated before any actual execution.
    _ptc_tools_ref.extend(t for t in tools if t.name not in ("bash_code_execute_tool", "request_answer_user_tool"))
    logger.info(
        " PTC tools injected into bash_tool (%d tools exposed via myrm_tools)",
        len(_ptc_tools_ref),
    )

    return tools


__all__ = [
    "SKILL_CORE_MAX",
    "SKILL_INLINE_THRESHOLD",
    "create_bash_process_kill_tool",
    "create_bash_process_list_tool",
    "create_bash_process_output_tool",
    "create_bash_tool",
    "create_batch_delegate_tasks_tool",
    "create_cancel_subagent_tool",
    "create_delegate_task_tool",
    "create_file_edit_tool",
    "create_file_read_tool",
    "create_file_write_tool",
    "create_glob_tool",
    "create_grep_tool",
    "create_select_skill_tool",
    "create_skill_analyze_tool",
    "create_skill_discovery_tool",
    "create_skill_manage_tool",
    "create_steer_subagent_tool",
    "get_meta_tools",
    "request_answer_user_tool",
]

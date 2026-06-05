"""Agent 工厂函数

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- config::LLMConfig (POS: LLM 配置类)
- skill_agent::SkillAgent (POS: 技能 Agent 实现，扩展 BaseAgent)
- middlewares::create_context_pipeline_middleware (POS: 上下文管道中间件工厂函数)
- types::AgentConfig (POS: Agent 配置类)
- toolkits.llms::create_litellm_model (POS: LiteLLM 模型创建函数)
- toolkits.mcp::MCPAgent, MCPConfig (POS: MCP 客户端管理与工具获取)
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM 基类)

[OUTPUT]
- create_skill_agent(): 工厂函数，创建 SkillAgent 实例（开箱即用，支持 LLMConfig 或 LLM 实例）

[POS]
Agent factory function. Provides create_skill_agent() to simplify Agent creation, supporting both LLMConfig and LLM instance patterns.

"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.config import LLMConfig
    from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
    from myrm_agent_harness.agent.security.types import PrivacyRoutingConfig
    from myrm_agent_harness.agent.skill_agent import SkillAgent
    from myrm_agent_harness.agent.skills import SkillMetadata
    from myrm_agent_harness.agent.types import AgentRuntimeSpec
    from myrm_agent_harness.backends.secrets.protocols import AgentSecretBackend
    from myrm_agent_harness.backends.skills.creation_protocols import SkillWriteBackend
    from myrm_agent_harness.backends.skills.discovery_protocols import (
        SkillDiscoveryBackend,
    )
    from myrm_agent_harness.backends.skills.protocols import (
        SkillBackend as SkillBackendProtocol,
    )
    from myrm_agent_harness.backends.skills.scanning_write_backend import (
        ScanningSkillWriteBackend,
    )
    from myrm_agent_harness.backends.skills.similarity import SkillSimilarityChecker
    from myrm_agent_harness.backends.skills.state_manager import SkillStateManager
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
    from myrm_agent_harness.toolkits.mcp.client import MCPServerConfigProtocol
    from myrm_agent_harness.toolkits.mcp.config import MCPConfig
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.storage.base import StorageProvider
    from myrm_agent_harness.toolkits.wiki import SemanticSearchFn

logger = logging.getLogger(__name__)

PTC_OVERHEAD_MULTIPLIER = 2
"""Multiplier for PTC bridge tool schema cost.
If MCP schema > bridge_cost * multiplier, PTC is more efficient."""

FALLBACK_PTC_BRIDGE_TOKENS = 450
"""Estimated PTC bridge tool schema overhead (skill_select_tool + discover_capability_tool)
when actual bridge tools are not yet available for measurement."""

CHARS_PER_TOKEN = 4.0


def _compute_direct_threshold(bridge_tools: Sequence[BaseTool] | None = None) -> int:
    """Compute the schema token threshold for direct-vs-PTC routing.

    Logic: if MCP schema tokens ≤ PTC bridge overhead * multiplier, use direct.
    The bridge overhead is measured from actual bridge tools when available,
    otherwise uses a conservative fallback estimate.
    """
    if bridge_tools:
        bridge_tokens = _estimate_schema_tokens(bridge_tools)
    else:
        bridge_tokens = FALLBACK_PTC_BRIDGE_TOKENS
    return bridge_tokens * PTC_OVERHEAD_MULTIPLIER


def _estimate_schema_tokens(tools: Sequence[BaseTool]) -> int:
    """Estimate schema tokens for a list of tools via chars/4 rule."""
    total_chars = 0
    for tool in tools:
        try:
            schema = tool.get_input_schema().schema() if hasattr(tool, "get_input_schema") else {}
        except Exception:
            schema = {}
        entry = {"name": tool.name, "description": tool.description or "", "parameters": schema}
        total_chars += len(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    return int(total_chars / CHARS_PER_TOKEN + 0.5)


def _config_to_dict(cfg: MCPServerConfigProtocol) -> dict[str, object]:
    """将 MCPServerConfigProtocol 转换为 dict（避免依赖 model_dump）"""
    return {
        "name": cfg.name,
        "type": cfg.type,
        "url": cfg.url,
        "command": cfg.command,
        "args": cfg.args,
        "description": cfg.description,
        "extra_params": cfg.extra_params,
    }


async def _route_mcp_servers(
    mcp_servers: Sequence[MCPServerConfigProtocol],
) -> tuple[list[SkillMetadata], list[BaseTool]]:
    """Route MCP servers into direct-tool or PTC-skill paths based on schema token cost.

    Returns:
        (mcp_skills, mcp_direct_tools): skills generated via PTC and tools for direct invocation.
    """
    from myrm_agent_harness.toolkits.mcp.connection_manager import (
        get_mcp_connection_manager,
    )

    ptc_servers: list[MCPConfig] = []
    mcp_skills: list[SkillMetadata] = []
    mcp_direct_tools: list[BaseTool] = []
    direct_threshold = _compute_direct_threshold()

    all_mcp_configs = cast("list[MCPConfig]", list(mcp_servers))
    manager = await get_mcp_connection_manager()

    # One warm session per server; a server that fails to start is skipped so a
    # single bad MCP can't abort agent creation (graceful degradation).
    for cfg in all_mcp_configs:
        try:
            conn = await manager.get_connection([cfg])
        except Exception as e:
            logger.warning("MCP server '%s' failed to connect, skipping: %s", cfg.name, e)
            continue

        server_tools = conn.tools_by_server.get(cfg.name) or next(
            (tools for tools in conn.tools_by_server.values() if tools), []
        )
        if not server_tools:
            logger.warning("MCP server '%s' exposed no tools, skipping", cfg.name)
            continue

        schema_tokens = _estimate_schema_tokens(server_tools)
        if schema_tokens <= direct_threshold:
            mcp_direct_tools.extend(server_tools)
            logger.info(
                "MCP hybrid: server '%s' (%d tools, ~%d tokens, threshold=%d) → direct",
                cfg.name,
                len(server_tools),
                schema_tokens,
                direct_threshold,
            )
        else:
            ptc_servers.append(cfg)
            logger.info(
                "MCP hybrid: server '%s' (%d tools, ~%d tokens, threshold=%d) → PTC/Skill",
                cfg.name,
                len(server_tools),
                schema_tokens,
                direct_threshold,
            )

    if ptc_servers:
        from myrm_agent_harness.agent.skills.mcp.core_generator import (
            mcp_skill_generator,
        )
        from myrm_agent_harness.agent.skills.runtime.registry import skill_registry

        logger.info(
            "MCP PTC skill generation: %d server(s): %s",
            len(ptc_servers),
            [s.name for s in ptc_servers],
        )
        mcp_skills = await mcp_skill_generator.generate_metadata_only(ptc_servers)
        logger.info("MCP PTC skill generation: produced %d skill(s)", len(mcp_skills))

        for skill in mcp_skills:
            if skill.mcp:
                server_configs = [cfg for cfg in ptc_servers if cfg.name == skill.mcp.server]
                if server_configs:
                    skill.mcp.config = [_config_to_dict(cfg) for cfg in server_configs]
                else:
                    skill.mcp.config = [_config_to_dict(cfg) for cfg in ptc_servers]
            skill_registry.register(skill)

    logger.info(
        "MCP hybrid summary: %d direct tools, %d PTC skills",
        len(mcp_direct_tools),
        len(mcp_skills),
    )
    return mcp_skills, mcp_direct_tools


async def create_skill_agent(
    spec: AgentRuntimeSpec,
    llm_config: LLMConfig | None = None,
    llm: BaseChatModel | None = None,
    executor: CodeExecutor | None = None,
    storage_backend: StorageProvider | None = None,
    skill_backend: SkillBackendProtocol | None = None,
    discovery_backend: SkillDiscoveryBackend | None = None,
    write_backend: SkillWriteBackend | None = None,
    secret_backend: AgentSecretBackend | None = None,
    memory_manager: MemoryManager | None = None,
    enable_memory_auto_extraction: bool = True,
    extraction_llm: BaseChatModel | None = None,
    middlewares: list[AgentMiddleware[Any, Any]] | None = None,
    tools: list[BaseTool] | None = None,
    deferred_tools: list[BaseTool] | None = None,
    context_schema: type | None = None,
    collect_artifacts: bool = False,
    on_artifacts_ready: BaseAgent.ArtifactReadyHandler | None = None,
    fallback_llm: BaseChatModel | None = None,
    safety_fallback_llm: BaseChatModel | None = None,
    escalation_target_llm: BaseChatModel | None = None,
    embedding_config=None,
    checkpointer: BaseCheckpointSaver | None | bool = True,
    privacy_routing_config: PrivacyRoutingConfig | None = None,
    event_log_backend: EventLogBackend | None = None,
    trusted_skill_ids: list[str] | None = None,
    skill_env_map: dict[str, dict[str, str]] | None = None,
    state_manager: SkillStateManager | None = None,
    default_skill_instances: dict[str, str] | None = None,
    global_env: dict[str, str] | None = None,
    on_skill_review_ready: Callable[[dict[str, object]], None] | None = None,
    model_resolver: object | None = None,
    wiki_base_dir: Path | str | None = None,
    wiki_search_fn: SemanticSearchFn | None = None,
    similarity_checker: SkillSimilarityChecker | None = None,
    on_session_cleanup: Callable[[Sequence[dict[str, str]], str | None], Awaitable[None]] | None = None,
    enable_file_tools: bool = True,
    enable_bash: bool = True,
    enable_llm_map: bool = False,
    enable_answer_tool: bool = True,
) -> SkillAgent:
    """创建 Skill Agent（纯净架构）

    **架构原则**：
    -  通用框架提供核心能力（LLM + 沙箱 + 存储）
    -  业务逻辑在业务层组装（业务工具、知识库、记忆等）
    -  用户配置沙箱后端（executor）和持久化存储（storage_backend）
    -  沙箱工作空间由 Executor 内部管理，用户无需关心

    **配置分类**：
    - 框架层配置：llm_config, executor, storage_backend, mcp_config
    - 业务层配置：search_service_cfg, memory_manager

    Args:
        llm_config: LLM 配置（推荐，内部将创建 LLM 实例）
        llm: LLM 实例（高级用户可直接传入自定义 LLM）
        executor: 沙箱后端（可选）
                 - 如果不传：根据配置自动创建（LocalExecutor）
                 - 如果传入：使用用户提供的自定义沙箱后端
                 - 沙箱工作空间由 Executor 内部管理，用户无需关心
        storage_backend: 持久化存储后端（可选）
                        - 用于工件持久化、技能资源存储等
                        - 如果不传：使用默认本地存储
                        - 支持：LocalStorageBackend 等实现 StorageProvider 的后端
        mcp_config: MCP 服务配置列表（可选，框架内部自动生成 MCP skills）
        skill_backend: 用户自定义技能后端（可选，用于动态加载用户 skills）
        memory_manager: 记忆管理器（可选），传入后框架自动管理 session 生命周期和 context 注入
        enable_memory_auto_extraction: 对话结束时自动从对话中提取记忆（需要 memory_manager）
        extraction_llm: 用于记忆提取的独立 LLM（可选，默认复用主 LLM，推荐用便宜模型降成本）
        middlewares: 中间件列表（可选，如果不提供将使用主 LLM 创建默认上下文管理中间件）
        system_prompt: 系统提示词
        tools: 业务工具列表（业务层创建，如 web_search_tool, wiki_tool 等）
        context_schema: Context schema 类
        recursion_limit: 递归限制，默认 50
        timeout_seconds: 超时时间（秒），默认 None 表示无超时
        parallel_tool_calls: 是否启用并行工具调用，None 使用 LLM 默认值
        collect_artifacts: 是否启用工件收集，默认 False（按需启用）
        on_artifacts_ready: 工件处理回调（依赖注入）
                     - 框架层在 run() 结束时内部调用，将 artifacts_ready 中间事件
                       转换为最终 artifacts 事件后再 yield
                     - 不传则不发任何工件事件（不暴露中间事件）

    Returns:
        SkillAgent 实例

    Example:
        >>> # 方式 1：最简单（使用 LLMConfig）
        >>> agent = await create_skill_agent(
        ...     llm_config=LLMConfig(model="gpt-4", api_key="sk-...")
        ... )
        >>>
        >>> # 方式 2：使用自定义沙箱后端（业务层创建）
        >>> executor = my_custom_executor  # 实现 CodeExecutor Protocol
        >>> agent = await create_skill_agent(
        ...     llm_config=llm_config,
        ...     executor=executor,
        ... )
        >>>
        >>> # 方式 3：使用持久化存储
        >>> from myrm_agent_harness.toolkits.storage import LocalStorageBackend
        >>> storage = LocalStorageBackend(base_path="./storage")
        >>> agent = await create_skill_agent(
        ...     llm_config=llm_config,
        ...     storage_backend=storage,
        ... )
        >>>
        >>> # 方式 4：带技能后端
        >>> from myrm_agent_harness.backends.skills import CompositeSkillBackend
        >>> skill_backend = CompositeSkillBackend(routes={
        ...     "/user/": SkillBackend.local("./user_skills"),
        ... })
        >>> agent = await create_skill_agent(
        ...     llm_config=llm_config,
        ...     skill_backend=skill_backend,
        ... )
        >>>
        >>> # 运行 Agent
        >>> async for event in agent.run("query"):
        ...     print(event["data"])
    """
    from myrm_agent_harness._distribution import assert_distribution_ready

    assert_distribution_ready()

    # 1. 处理 LLM 实例（支持两种方式）
    if llm is None:
        # 方式 1：从 llm_config 创建 LLM
        if llm_config is None:
            raise ValueError(
                "Must provide either 'llm_config' or 'llm'. "
                "For quick start, use: llm_config=LLMConfig(model='gpt-4', api_key='sk-...')"
            )

        from myrm_agent_harness.toolkits.llms import create_litellm_model

        kwargs = {
            "model": llm_config.model,
            "api_key": llm_config.api_key,
            "base_url": llm_config.base_url,
            "streaming": llm_config.streaming,
            **(llm_config.model_kwargs or {}),
        }
        if llm_config.temperature is not None:
            kwargs["temperature"] = llm_config.temperature

        llm = create_litellm_model(**kwargs)
        logger.info(f" 创建 LLM 实例: {llm_config.model}")

    # 1.5 Privacy-aware model routing (wrap LLM if configured)
    if privacy_routing_config is not None and privacy_routing_config.local_model is not None:
        from myrm_agent_harness.toolkits.llms import (
            create_litellm_model as _create_model,
        )
        from myrm_agent_harness.toolkits.llms.routing import PrivacyRoutingModel

        local_llm = _create_model(
            model=privacy_routing_config.local_model,
            base_url=privacy_routing_config.local_base_url,
            api_key=privacy_routing_config.local_api_key or "",
            temperature=0.2,
            streaming=True,
        )
        llm = PrivacyRoutingModel(
            cloud_llm=llm,
            local_llm=local_llm,
            routing_config=privacy_routing_config,
        )
        logger.info(
            " Privacy routing enabled: cloud=%s, local=%s, s2=%s, s3=%s",
            type(llm.cloud_llm).__name__,
            privacy_routing_config.local_model,
            privacy_routing_config.s2_strategy,
            privacy_routing_config.s3_strategy,
        )

    # 2. 处理 MCP Config（智能混合调用模式：自动按 schema token 估算分流）
    mcp_skills: list[SkillMetadata] = []
    mcp_direct_tools: list[BaseTool] = []
    if spec.mcp_servers:
        mcp_skills, mcp_direct_tools = await _route_mcp_servers(spec.mcp_servers)

    # 2.5 Generate tools from OpenAPI service configs
    openapi_tools: list[BaseTool] = []
    if spec.openapi_services:
        from myrm_agent_harness.toolkits.openapi_bridge import (
            OpenAPIBridge,
            OpenAPIServiceConfig,
        )

        bridge = OpenAPIBridge()
        for svc_dict in spec.openapi_services:
            try:
                svc_config = OpenAPIServiceConfig.model_validate(svc_dict)
                if svc_config.enabled:
                    svc_tools = await bridge.get_tools(svc_config)
                    openapi_tools.extend(svc_tools)
            except Exception as e:
                logger.warning(f"Failed to load OpenAPI service: {e}")

        if openapi_tools:
            logger.info(f"OpenAPI Bridge: generated {len(openapi_tools)} tools")

    if tools is None:
        tools = []
    tools = list(tools) + openapi_tools + mcp_direct_tools

    # 3. 合并 MCP skills 和用户自定义 skills（智能整合）
    # 注意：skill_backend 需要用户明确配置（包含技能存储路径），不能从 storage_backend 自动创建
    final_skill_backend: SkillBackendProtocol | None = skill_backend
    if mcp_skills:
        from myrm_agent_harness.backends.skills import (
            CompositeSkillBackend,
            InMemorySkillBackend,
        )
        from myrm_agent_harness.backends.skills.protocols import (
            SkillBackend as SkillBackendProto,
        )

        mcp_backend = InMemorySkillBackend(skills=mcp_skills)

        if skill_backend is None:
            # 场景 1: 只有 MCP skills
            final_skill_backend = mcp_backend
            logger.info(" 使用 MCP Skills（InMemorySkillBackend）")

        elif isinstance(skill_backend, CompositeSkillBackend):
            # 场景 3: 用户已经混合了多个后端，扁平化合并
            # 避免嵌套 CompositeSkillBackend
            new_routes: dict[str, SkillBackendProto] = {"/mcp/": mcp_backend}
            new_routes.update(skill_backend.routes)
            final_skill_backend = CompositeSkillBackend(
                routes=new_routes,
                default=skill_backend.default,
            )
            logger.info(f" 扁平化合并 MCP Skills + 用户 {len(skill_backend.routes)} 个后端路由")

        else:
            # 场景 2: 用户传了简单后端
            routes: dict[str, SkillBackendProto] = {
                "/mcp/": mcp_backend,
                "/user/": skill_backend,
            }
            final_skill_backend = CompositeSkillBackend(routes=routes)
            logger.info(" 合并 MCP Skills + 用户 Skills（CompositeSkillBackend）")

    # 3.5 注入 SkillBackend 到 SkillMdLoader（使其能加载存储技能文档）
    if final_skill_backend is not None:
        from myrm_agent_harness.agent.skills.runtime.loader import skill_md_loader

        skill_md_loader.set_backend(final_skill_backend)

    # 4. 创建配置
    from myrm_agent_harness.agent.types import AgentRuntimeConfig, EngineParams

    engine_params_dict = spec.engine_params or {}
    if isinstance(engine_params_dict, dict):
        from dataclasses import fields as dataclass_fields

        known_fields = {field.name for field in dataclass_fields(EngineParams)}
        filtered_params = {key: value for key, value in engine_params_dict.items() if key in known_fields}
        engine_params = EngineParams(**filtered_params) if filtered_params else EngineParams()
    else:
        engine_params = EngineParams()

    config = AgentRuntimeConfig(
        recursion_limit=spec.max_iterations,
        timeout_seconds=engine_params.timeout_seconds,
        parallel_tool_calls=engine_params.enable_parallel_tool_calls,
        collect_artifacts=collect_artifacts,
        locale=spec.locale,
        channel_name=spec.channel_name,
        security_config=spec.security_config,
        engine_params=engine_params,
    )

    # 5. 处理 checkpointer
    final_checkpointer: BaseCheckpointSaver | None = None
    if checkpointer is True:
        from langgraph.checkpoint.memory import MemorySaver

        final_checkpointer = MemorySaver()
        logger.info(" 使用默认 MemorySaver checkpointer（启用 HITL）")
    elif checkpointer is False or checkpointer is None:
        final_checkpointer = None
        logger.info(" 禁用 checkpointer（禁用 HITL）")
    else:
        final_checkpointer = checkpointer
        logger.info(f" 使用自定义 checkpointer: {type(checkpointer).__name__}")

    # 6. 构建中间件列表
    final_middlewares: list[AgentMiddleware[object, object]] | None = middlewares
    if final_middlewares is None:
        from myrm_agent_harness.agent.middlewares import (
            create_context_pipeline_middleware,
        )

        final_middlewares = []
        if engine_params.enable_context_compression:
            final_middlewares.append(create_context_pipeline_middleware(llm=llm))
            logger.info(f" 使用主 LLM 创建默认上下文管理中间件: {type(llm).__name__}")
        else:
            logger.info(" 上下文管理中间件已通过 EngineParams 禁用")
    else:
        logger.info(" 使用用户提供的自定义中间件")

    # 8. 包装 write_backend 为 ScanningSkillWriteBackend（强制安全扫描 + 可选 LLM 审计）
    final_write_backend: ScanningSkillWriteBackend | None = None
    if write_backend is not None:
        from myrm_agent_harness.agent.skills.runtime.loader import skill_md_loader
        from myrm_agent_harness.backends.skills.scanning_write_backend import (
            ScanningSkillWriteBackend,
        )

        llm_auditor_instance = None
        auxiliary = fallback_llm or llm
        if auxiliary is not None:
            from myrm_agent_harness.backends.skills.scanning.llm_auditor import (
                SkillLLMAuditor,
            )

            llm_auditor_instance = SkillLLMAuditor(llm=auxiliary)
            logger.info(" LLM 安全审计已启用（语义级威胁检测）")

        final_write_backend = ScanningSkillWriteBackend(
            inner=write_backend,
            loader=skill_md_loader,
            llm_auditor=llm_auditor_instance,
        )
        logger.info(" ScanningSkillWriteBackend 已启用（强制安全扫描）")

    # 9. 创建并返回 SkillAgent
    from myrm_agent_harness.agent.skill_agent import SkillAgent

    return SkillAgent(
        llm=llm,
        executor=executor,
        storage_backend=storage_backend,
        skill_backend=final_skill_backend,
        discovery_backend=discovery_backend,
        write_backend=final_write_backend,
        secret_backend=secret_backend,
        memory_manager=memory_manager,
        enable_memory_auto_extraction=enable_memory_auto_extraction,
        extraction_llm=extraction_llm,
        middlewares=final_middlewares,
        system_prompt=spec.system_prompt,
        tools=tools or [],
        deferred_tools=deferred_tools or [],
        context_schema=context_schema,
        config=config,
        on_artifacts_ready=on_artifacts_ready,
        fallback_llm=fallback_llm,
        safety_fallback_llm=safety_fallback_llm,
        escalation_target_llm=escalation_target_llm,
        embedding_config=embedding_config,
        checkpointer=final_checkpointer,
        event_log_backend=event_log_backend,
        trusted_skill_ids=trusted_skill_ids,
        skill_env_map=skill_env_map,
        desired_skill_ids=spec.skill_ids,
        skill_configs=spec.skill_configs,
        state_manager=state_manager,
        default_skill_instances=default_skill_instances,
        global_env=global_env,
        on_skill_review_ready=on_skill_review_ready,
        wiki_base_dir=wiki_base_dir,
        wiki_search_fn=wiki_search_fn,
        similarity_checker=similarity_checker,
        on_session_cleanup=on_session_cleanup,
        enable_file_tools=enable_file_tools,
        enable_bash=enable_bash,
        enable_llm_map=enable_llm_map,
        enable_answer_tool=enable_answer_tool,
        available_tool_names=frozenset(spec.allowed_tools) if spec.allowed_tools else None,
        available_tool_groups=frozenset(spec.tool_groups) if spec.tool_groups else None,
    )

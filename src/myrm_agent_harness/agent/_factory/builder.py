"""SkillAgent assembly pipeline — LLM, MCP, skills, middleware, and runtime config.

[INPUT]
- agent._factory.mcp_routing::route_mcp_servers (POS: MCP hybrid direct/PTC routing)
- agent.skill_agent::SkillAgent (POS: Skill Agent implementation)
- agent.types::AgentRuntimeSpec, AgentRuntimeConfig (POS: Agent runtime types)

[OUTPUT]
- create_skill_agent(): assemble and return a configured SkillAgent instance

[POS]
SkillAgent factory assembly. Wires LLM, MCP/OpenAPI tools, skill backends, middleware, and runtime config.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.storage.base import StorageProvider
    from myrm_agent_harness.toolkits.wiki import SemanticSearchFn

from myrm_agent_harness.agent._factory.mcp_routing import (
    apply_aggregate_threshold,
    route_mcp_servers,
)

logger = logging.getLogger(__name__)


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
    """Create a SkillAgent instance (framework assembly entry)."""
    from myrm_agent_harness._distribution import assert_distribution_ready

    assert_distribution_ready()

    if llm is None:
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

    mcp_skills: list[SkillMetadata] = []
    mcp_direct_tools: list[BaseTool] = []
    if spec.mcp_servers:
        mcp_skills, mcp_direct_tools = await route_mcp_servers(spec.mcp_servers)

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
    mcp_kept, mcp_overflow = apply_aggregate_threshold(mcp_direct_tools)
    tools = list(tools) + openapi_tools + mcp_kept

    if deferred_tools is None:
        deferred_tools = []
    if mcp_overflow:
        deferred_tools = list(deferred_tools) + mcp_overflow

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
            final_skill_backend = mcp_backend
            logger.info(" 使用 MCP Skills（InMemorySkillBackend）")

        elif isinstance(skill_backend, CompositeSkillBackend):
            new_routes: dict[str, SkillBackendProto] = {"/mcp/": mcp_backend}
            new_routes.update(skill_backend.routes)
            final_skill_backend = CompositeSkillBackend(
                routes=new_routes,
                default=skill_backend.default,
            )
            logger.info(f" 扁平化合并 MCP Skills + 用户 {len(skill_backend.routes)} 个后端路由")

        else:
            routes: dict[str, SkillBackendProto] = {
                "/mcp/": mcp_backend,
                "/user/": skill_backend,
            }
            final_skill_backend = CompositeSkillBackend(routes=routes)
            logger.info(" 合并 MCP Skills + 用户 Skills（CompositeSkillBackend）")

    if final_skill_backend is not None:
        from myrm_agent_harness.agent.skills.runtime.loader import skill_md_loader

        skill_md_loader.set_backend(final_skill_backend)

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

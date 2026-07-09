"""Skill Agent - Extends BaseAgent with the skill system.

[INPUT]
- base_agent::BaseAgent (POS: Lightweight Agent base class with streaming, token tracking, and artifacts.)
- _skill_agent_context (POS: Module-level ContextVar management and background task utilities.)
- _skill_agent_review::SkillAgentReviewMixin (POS: Session-end review mixin for SkillAgent.)
- _skill_agent_tools::SkillAgentToolsMixin (POS: Tool building mixin for SkillAgent.)
- skills::SkillMetadata (POS: Skill metadata type)
- types::AgentRuntimeConfig (POS: Agent runtime config)
- event_log.protocols::EventLogBackend (POS: Event log backend protocol)
- meta_tools.skills.select::get_skill_document (POS: Load skill SOP document for explicit injection)
- skills.evolution.infra.integration::get_global_evolution_integration (POS: Integration helpers for skill evolution system.)

[OUTPUT]
- SkillAgent: Skill Agent — extends BaseAgent with skill system, hooks, and session lifecycle.
- wait_all_background_tasks: Graceful shutdown utility for background tasks.

[POS]
Skill Agent implementation. Extends BaseAgent with the skill system, meta-tools,
workspace management, and the Hook system.
"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent._skill_agent_context import (
    SkillAgentContextMixin,
    add_loaded_skill,
    get_loaded_skills,
    reset_loaded_skills,
    set_loaded_skills,
    set_memory_manager,
    set_storage_backend,
    track_background_task,
    wait_all_background_tasks,
)
from myrm_agent_harness.agent._skill_agent_review import SkillAgentReviewMixin
from myrm_agent_harness.agent._skill_agent_tools import SkillAgentToolsMixin
from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.skill_agent_preload_mixin import SkillAgentPreloadMixin
from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
from myrm_agent_harness.agent.skills import SkillMetadata
from myrm_agent_harness.agent.types import AgentRuntimeConfig
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from pathlib import Path

    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.messages import BaseMessage
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from myrm_agent_harness.backends.secrets.protocols import AgentSecretBackend
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
    from myrm_agent_harness.backends.skills.types import SkillInstance
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig
    from myrm_agent_harness.toolkits.storage.base import StorageProvider
    from myrm_agent_harness.toolkits.wiki import (
        SemanticSearchFn,
        WikiCompiler,
        WikiStructure,
    )
    from myrm_agent_harness.utils.chat_utils import ChatHistoryReq
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

logger = get_agent_logger(__name__)

__all__ = ["SkillAgent", "wait_all_background_tasks"]


class SkillAgent(
    SkillAgentPreloadMixin,
    SkillAgentToolsMixin,
    SkillAgentReviewMixin,
    SkillAgentContextMixin,
    BaseAgent,
):
    """技能 Agent - 扩展 BaseAgent

    在 BaseAgent 基础上添加:
    - 技能后端(SkillBackend)
    - 元工具(file_write/edit/bash/skill_select)
    - 技能工作空间管理

    特性:技能系统,渐进式披露,完全自主决策,流式事件,兼容官方中间件
    """

    def __init__(
        self,
        llm: BaseChatModel,
        executor: "CodeExecutor | None" = None,
        storage_backend: "StorageProvider | None" = None,
        skill_backend: "SkillBackendProtocol | None" = None,
        discovery_backend: "SkillDiscoveryBackend | None" = None,
        write_backend: "ScanningSkillWriteBackend | None" = None,
        secret_backend: "AgentSecretBackend | None" = None,
        memory_manager: "MemoryManager | None" = None,
        enable_memory_auto_extraction: bool = True,
        extraction_llm: BaseChatModel | None = None,
        middlewares: "list[AgentMiddleware[Any, Any]] | None" = None,
        system_prompt: str | None = None,
        tools: list[BaseTool] | None = None,
        discoverable_tools: list[BaseTool] | None = None,
        context_schema: type | None = None,
        config: AgentRuntimeConfig | None = None,
        on_artifacts_ready: "BaseAgent.ArtifactReadyHandler | None" = None,
        user_id: str | None = None,
        model_resolver: object | None = None,
        fallback_llm: BaseChatModel | None = None,
        safety_fallback_llm: BaseChatModel | None = None,
        escalation_target_llm: BaseChatModel | None = None,
        embedding_config: "EmbeddingConfig | None" = None,
        checkpointer: "BaseCheckpointSaver | None" = None,
        event_log_backend: EventLogBackend | None = None,
        trusted_skill_ids: list[str] | None = None,
        skill_env_map: dict[str, dict[str, str]] | None = None,
        desired_skill_ids: list[str] | None = None,
        skill_configs: dict[str, dict] | None = None,
        state_manager: "SkillStateManager | None" = None,
        default_skill_instances: dict[str, str] | None = None,
        global_env: dict[str, str] | None = None,
        on_skill_review_ready: "Callable[[dict[str, object]], None] | None" = None,
        wiki_base_dir: "Path | str | None" = None,
        wiki_search_fn: "SemanticSearchFn | None" = None,
        similarity_checker: "SkillSimilarityChecker | None" = None,
        on_session_cleanup: "Callable[[Sequence[dict[str, str]], str | None], Awaitable[None]] | None" = None,
        on_loaded_skills_persist: "Callable[[list[str], str | None], Awaitable[None]] | None" = None,
        enable_file_tools: bool = True,
        enable_bash: bool = True,
        enable_answer_tool: bool = False,
        enable_planning: bool = False,
        task_workspace_root: str | None = None,
        available_tool_names: frozenset[str] | None = None,
        available_tool_groups: frozenset[str] | None = None,
        library_skill_names: frozenset[str] | None = None,
    ) -> None:
        self.model_resolver = model_resolver
        super().__init__(
            llm=llm,
            executor=executor,
            middlewares=middlewares,
            system_prompt=system_prompt,
            tools=tools,
            discoverable_tools=discoverable_tools,
            context_schema=context_schema,
            config=config,
            on_artifacts_ready=on_artifacts_ready,
            fallback_llm=fallback_llm,
            safety_fallback_llm=safety_fallback_llm,
            escalation_target_llm=escalation_target_llm,
            checkpointer=checkpointer,
            event_log_backend=event_log_backend,
        )

        self.skill_configs = skill_configs
        self.skill_backend = skill_backend
        self.discovery_backend = discovery_backend
        self.write_backend = write_backend
        self.storage_backend = storage_backend
        self.secret_backend = secret_backend
        self.state_manager = state_manager
        self.memory_manager: MemoryManager | None = memory_manager
        self._enable_memory_auto_extraction = enable_memory_auto_extraction
        self._extraction_llm = extraction_llm
        self._active_skill: SkillMetadata | None = None
        self._user_id = user_id
        self._on_skill_review_ready = on_skill_review_ready
        self._embedding_config: EmbeddingConfig | None = embedding_config
        self._default_skill_instances = default_skill_instances or {}
        self._trusted_skill_ids: frozenset[str] = frozenset(trusted_skill_ids) if trusted_skill_ids else frozenset()
        self._skill_env_map = skill_env_map
        self._desired_skill_ids: list[str] | None = desired_skill_ids
        self._similarity_checker: SkillSimilarityChecker | None = similarity_checker
        self._global_env = global_env
        self._wiki_base_dir = wiki_base_dir
        self._wiki_search_fn: SemanticSearchFn | None = wiki_search_fn
        self._wiki_compiler: WikiCompiler | None = None
        self._wiki_structure: WikiStructure | None = None
        self._on_session_cleanup = on_session_cleanup
        self._on_loaded_skills_persist = on_loaded_skills_persist
        self._enable_file_tools = enable_file_tools
        self._enable_bash = enable_bash
        self._enable_answer_tool = enable_answer_tool
        self._enable_planning = enable_planning
        self._task_workspace_root = task_workspace_root
        self._available_tool_names = available_tool_names
        self._available_tool_groups = available_tool_groups
        self._library_skill_names = library_skill_names

    async def _get_cached_skills(self) -> list[SkillMetadata]:
        """Load skills from backend (no caching to enable hot reload).

        Applies user trust overrides: skills whose storage_skill_id is in
        _trusted_skill_ids are elevated to SkillTrust.TRUSTED.

        Note: Previously this method cached skills in memory, which broke hot reload.
        Now it always loads from backend to ensure latest skill versions are used.
        The backend (e.g., LocalSkillBackend) uses SQLiteSkillSnapshot for fast O(N) reads.
        """
        if self.skill_backend is None:
            return []

        skills: list[SkillMetadata] = []
        try:
            if self._desired_skill_ids is not None and hasattr(self.skill_backend, "load_skills"):
                skills = await self.skill_backend.load_skills(self._desired_skill_ids)
                logger.debug(
                    "Loaded %d/%d skills from skill_backend (desired_ids=%s)",
                    len(skills),
                    len(self._desired_skill_ids),
                    self._desired_skill_ids,
                )
            else:
                skills = await self.skill_backend.list_skills()
                logger.debug(
                    "Loaded %d skills from skill_backend (all available)",
                    len(skills),
                )

            if self._trusted_skill_ids:
                from myrm_agent_harness.backends.skills.types import SkillTrust

                for skill in skills:
                    sid = skill.storage_skill_id or skill.name
                    if sid in self._trusted_skill_ids and skill.trust < SkillTrust.TRUSTED:
                        skill.trust = SkillTrust.TRUSTED
        except Exception as e:
            logger.warning("Failed to load skills from skill_backend: %s", e)
            skills = []

        return skills

    async def load_skill_instance(self, skill_name: str, instance_name: str) -> "SkillInstance":
        """Load a skill instance with configuration and state.

        Provides programmatic access to multi-instance skill support. Combines:
        - Base SkillMetadata from backend
        - SkillInstanceConfig (env/config overrides)
        - Runtime state (persisted)

        This method enables business layer to load and use skill instances
        without modifying core Agent logic.

        Args:
            skill_name: Skill name (e.g., "github_skill")
            instance_name: Instance name (e.g., "personal", "work")

        Returns:
            SkillInstance object with merged configuration

        Raises:
            ValueError: If state_manager not configured or instance not found

        Example:
            >>> agent = SkillAgent(
            ...     llm=llm,
            ...     skill_backend=backend,
            ...     state_manager=SkillStateManager()
            ... )
            >>> instance = await agent.load_skill_instance("github_skill", "personal")
            >>> token = instance.get_env("GITHUB_TOKEN")
        """
        if self.state_manager is None:
            raise ValueError("state_manager not configured. Pass SkillStateManager to SkillAgent.__init__")

        if self.skill_backend is None:
            raise ValueError("skill_backend not configured")

        instance = await self.state_manager.load_instance(
            backend=self.skill_backend,
            skill_name=skill_name,
            instance_name=instance_name,
        )

        if instance is None:
            raise ValueError(f"Skill instance not found: {skill_name}.{instance_name}")

        return instance

    def _build_middlewares(self) -> "list[AgentMiddleware[Any, Any]]":
        """构建中间件链(覆盖 BaseAgent)"""
        return super()._build_middlewares()

    def _inject_action_space_metrics(self) -> None:
        """Inject runtime action space counts into the session event logger summary."""
        try:
            from myrm_agent_harness.agent.middlewares._session_context import (
                get_event_logger,
            )

            el = get_event_logger()
            skills = getattr(self, "_runtime_skill_count", None)
            tools = getattr(self, "_runtime_tool_count", None)
            if el is not None and skills is not None and tools is not None:
                el.set_action_space_metrics(skills, tools)
        except Exception:
            pass

    async def run(
        self,
        query: str | list[dict[str, object]] | object,
        chat_history: "ChatHistoryReq | list[BaseMessage] | None" = None,
        message_id: str | None = None,
        context: dict[str, object] | None = None,
        cancel_token: "CancellationToken | None" = None,
        steering_token: "SteeringToken | None" = None,
        timezone: str | None = None,
        active_skill: SkillMetadata | None = None,
    ) -> AsyncGenerator[dict[str, object]]:
        """流式运行 Agent(覆盖 BaseAgent),增加 Hook 生命周期和记忆会话管理."""
        if active_skill is None and isinstance(query, str):
            query, active_skill = await self._preload_explicit_skill(query)

        from myrm_agent_harness.backends.skills.usage_recorder import reset_turn_usage_dedupe

        reset_turn_usage_dedupe()
        self._active_skill = active_skill
        reset_loaded_skills()
        cached_skills = await self._get_cached_skills()
        from myrm_agent_harness.agent.skills.runtime.session_skills_rehydrate import (
            SESSION_LOADED_SKILL_NAMES_CONTEXT_KEY,
            rehydrate_loaded_skills_from_history,
        )

        session_skill_names: list[str] | None = None
        if context:
            raw_names = context.get(SESSION_LOADED_SKILL_NAMES_CONTEXT_KEY)
            if isinstance(raw_names, list):
                session_skill_names = [str(name) for name in raw_names if name]

        rehydrated = rehydrate_loaded_skills_from_history(
            chat_history,
            cached_skills,
            session_skill_names,
        )
        if rehydrated:
            set_loaded_skills(rehydrated)
        if active_skill:
            if not any(s.name == active_skill.name for s in get_loaded_skills()):
                add_loaded_skill(active_skill)
        await self._init_hook_lifecycle(active_skill, message_id, query)
        self._begin_memory_session(context, message_id)

        self._inject_action_space_metrics()

        assistant_chunks: list[str] = []
        try:
            async for event in super().run(
                query=query,
                chat_history=chat_history,
                message_id=message_id,
                context=context,
                cancel_token=cancel_token,
                steering_token=steering_token,
                timezone=timezone,
            ):
                if isinstance(event, dict) and event.get("type") == "message":
                    chunk = event.get("data")
                    if isinstance(chunk, str):
                        assistant_chunks.append(chunk)
                yield event
        finally:
            # Capture loaded skills BEFORE resetting context vars
            active_skills_list = [s.name for s in get_loaded_skills()]
            run_chat_id: str | None = None
            if context:
                raw_chat_id = context.get("chat_id")
                if raw_chat_id:
                    run_chat_id = str(raw_chat_id)

            # Create a background task for cleanup to ensure zero blocking of the UI thread
            async def _background_cleanup(active_skills: list[str], chat_id: str | None) -> None:
                logger.info("_background_cleanup executing for skills: %s", active_skills)
                try:
                    await self._cleanup_session(
                        query,
                        chat_history,
                        assistant_chunks,
                        active_skills,
                        run_chat_id=chat_id,
                    )
                except Exception as e:
                    logger.error("Background session cleanup failed: %s", e, exc_info=True)

            logger.info("Creating _background_cleanup task")
            task = asyncio.create_task(_background_cleanup(active_skills_list, run_chat_id))
            track_background_task(task)

            try:
                set_storage_backend(None)
                set_memory_manager(None)
                reset_loaded_skills()
            except Exception as ctx_error:
                logger.error("Error cleaning up ContextVar: %s", ctx_error, exc_info=True)

    async def _init_hook_lifecycle(
        self,
        skill: SkillMetadata | None,
        message_id: str | None,
        query: str | list[dict[str, object]],
    ) -> None:
        """Initialize HookExecutor from Skill hooks and framework-level defaults."""
        from myrm_agent_harness.agent.hooks import (
            bootstrap_hook_registry,
        )
        from myrm_agent_harness.agent.middlewares._session_context import (
            get_event_logger,
        )
        from myrm_agent_harness.agent.streaming.broadcast.tool_call_broadcaster import (
            register_to_hook_registry,
        )

        registry = bootstrap_hook_registry()

        if skill and skill.hooks:
            for event, hook_def in skill.hooks:
                registry.register(event, hook_def)

        # Only register broadcaster if it's not already registered
        if not any(h.fn.__name__ == "on_pre_tool_use" for h in registry._hooks.get("pre_tool_use", [])):
            register_to_hook_registry(registry, get_event_logger())

        # Register evolution sliding window hooks if integration is active
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            get_global_evolution_integration,
        )

        evo = get_global_evolution_integration()
        if evo is not None:
            evo.register_hooks(registry)

        # Register HITL correction learning hook (converts approval edits/rejects into memory)
        from myrm_agent_harness.agent.hooks.types import CallableHookDefinition, HookEvent
        from myrm_agent_harness.agent.middlewares.approval.correction_learning import CorrectionLearningHook

        if not any(
            getattr(h, "fn", None) and getattr(h.fn, "__name__", "") == "on_approval_correction"
            for h in registry._hooks.get(HookEvent.APPROVAL_CORRECTION, [])
        ):
            correction_hook = CorrectionLearningHook()
            registry.register(
                HookEvent.APPROVAL_CORRECTION,
                CallableHookDefinition(fn=correction_hook.on_approval_correction),
            )

        if skill and skill.hooks:
            logger.info("Hooks activated: %s (%d hooks)", skill.name, registry.total_count)
        else:
            logger.debug(" Framework-level hooks activated (%d hooks)", registry.total_count)

    def _begin_memory_session(self, context: dict[str, object] | None, message_id: str | None) -> None:
        if self.memory_manager is not None:
            chat_id = str((context or {}).get("chat_id", message_id or "default"))
            from myrm_agent_harness.agent.hooks import get_hook_executor

            executor = get_hook_executor()
            registry = executor.registry if executor else None
            self.memory_manager.begin_session(chat_id, hook_registry=registry)

    async def close(self) -> None:
        """Release resources held by this agent."""
        self.memory_manager = None

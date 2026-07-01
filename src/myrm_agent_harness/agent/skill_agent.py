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
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent._skill_agent_context import (
    add_loaded_skill,
    get_loaded_skills,
    reset_loaded_skills,
    set_memory_manager,
    set_storage_backend,
    track_background_task,
    wait_all_background_tasks,
)
from myrm_agent_harness.agent._skill_agent_review import SkillAgentReviewMixin
from myrm_agent_harness.agent._skill_agent_tools import SkillAgentToolsMixin
from myrm_agent_harness.agent.base_agent import BaseAgent
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


class SkillAgent(SkillAgentToolsMixin, SkillAgentReviewMixin, BaseAgent):
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
        deferred_tools: list[BaseTool] | None = None,
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
        enable_file_tools: bool = True,
        enable_bash: bool = True,
        enable_answer_tool: bool = True,
        available_tool_names: frozenset[str] | None = None,
        available_tool_groups: frozenset[str] | None = None,
    ) -> None:
        self.model_resolver = model_resolver
        super().__init__(
            llm=llm,
            executor=executor,
            middlewares=middlewares,
            system_prompt=system_prompt,
            tools=tools,
            deferred_tools=deferred_tools,
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
        self._enable_file_tools = enable_file_tools
        self._enable_bash = enable_bash
        self._enable_answer_tool = enable_answer_tool
        self._available_tool_names = available_tool_names
        self._available_tool_groups = available_tool_groups

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

    _USE_SKILL_PATTERN = re.compile(r"^\[use\s+([\w,\s-]+)\]\s*(.*)", re.DOTALL)

    _TOKEN_BUDGET_MAX = 12000
    """Soft cap (in estimated characters) for combined SOP injection to prevent token explosion."""

    async def _preload_explicit_skill(self, query: str) -> tuple[str, SkillMetadata | None]:
        """Detect ``[use skill_name]`` or ``[use s1,s2,s3]`` prefix and pre-inject SOP(s).

        Supports both single-skill and multi-skill (bundle) invocation. When multiple
        skill names are comma-separated, all SOPs are merged into a single injection,
        respecting ``_TOKEN_BUDGET_MAX`` to prevent token explosion.

        The ``[instruction: ...]`` suffix in the ``[use ...]`` tag is also supported
        for ephemeral bundle guidance.

        Returns:
            (modified_query, first_matched_skill_meta) — original query unchanged on failure.
        """
        match = self._USE_SKILL_PATTERN.match(query)
        if not match:
            return query, None

        raw_names = match.group(1)
        user_args = match.group(2).strip()

        skill_names = [n.strip() for n in raw_names.split(",") if n.strip()]
        if not skill_names:
            return query, None

        if not self.skill_backend:
            logger.debug("Explicit skill(s) %s requested but no skill_backend", skill_names)
            return query, None

        skills = await self._get_cached_skills()
        skill_map = {s.name: s for s in skills}

        matched: list[SkillMetadata] = []
        for name in skill_names:
            meta = skill_map.get(name)
            if meta:
                matched.append(meta)
            else:
                logger.info("Explicit skill '%s' not found in %d skills — skipped", name, len(skills))

        if not matched:
            return query, None

        from myrm_agent_harness.agent.meta_tools.skills.select import (
            get_skill_document,
        )

        sop_sections: list[str] = []
        total_chars = 0
        loaded_names: list[str] = []

        for skill_meta in matched:
            try:
                sop_doc = await get_skill_document(skill_meta, self.skill_backend)
            except Exception:
                logger.warning("Failed to preload SOP for skill '%s' — skipped", skill_meta.name, exc_info=True)
                continue

            if not sop_doc or "\nError: " in sop_doc:
                logger.info("Empty or errored SOP for skill '%s' — skipped", skill_meta.name)
                continue

            if total_chars + len(sop_doc) > self._TOKEN_BUDGET_MAX and sop_sections:
                logger.warning(
                    "Token budget exceeded after %d skills (%d chars), skipping '%s'",
                    len(sop_sections),
                    total_chars,
                    skill_meta.name,
                )
                break

            section_parts = [f"--- Skill: {skill_meta.name} ---", sop_doc]

            file_listing = self._list_skill_auxiliary_files(skill_meta)
            if file_listing:
                section_parts.append(file_listing)

            if not skill_meta.available:
                reason = skill_meta.unavailable_reason or "dependency requirements not met"
                section_parts.append(f"WARNING: Skill '{skill_meta.name}' is UNAVAILABLE ({reason}).")

            sop_sections.append("\n".join(section_parts))
            total_chars += len(sop_doc)
            loaded_names.append(skill_meta.name)

        if not sop_sections:
            return query, None

        is_bundle = len(sop_sections) > 1
        names_str = ", ".join(loaded_names)

        if is_bundle:
            header = (
                f"[IMPORTANT: The following {len(sop_sections)} skills have been preloaded as a bundle: "
                f"{names_str}. Follow ALL their SOP instructions. Do NOT call skill_select_tool "
                f"for these skills — their content is already provided below.]"
            )
        else:
            header = (
                f'[IMPORTANT: The skill "{loaded_names[0]}" has been preloaded by the user. '
                f"Follow its SOP instructions immediately. Do NOT call skill_select_tool "
                f"for this skill — its content is already provided below.]"
            )

        parts = [header, "", *sop_sections]

        if user_args:
            parts.append("")
            parts.append(user_args)

        logger.info(
            "Preloaded %d skill(s) %s — SOP injected (%d chars), user_args='%s'",
            len(sop_sections),
            loaded_names,
            total_chars,
            user_args[:80],
        )
        return "\n".join(parts), matched[0]

    @staticmethod
    def _list_skill_auxiliary_files(skill_meta: SkillMetadata) -> str:
        """List auxiliary files under a skill's storage directory.

        Scans the allowed subdirectories (scripts/, references/, templates/, assets/)
        and returns a formatted listing for the LLM. Returns empty string if the skill
        has no storage path or no auxiliary files exist.
        """
        if not skill_meta.storage_path:
            return ""

        from pathlib import Path

        skill_dir = Path(skill_meta.storage_path)
        if not skill_dir.is_dir():
            return ""

        allowed_dirs = ("scripts", "references", "templates", "assets")
        file_entries: list[str] = []

        for subdir_name in allowed_dirs:
            subdir = skill_dir / subdir_name
            if not subdir.is_dir():
                continue
            for file_path in sorted(subdir.rglob("*")):
                if file_path.is_file():
                    rel_path = file_path.relative_to(skill_dir)
                    file_entries.append(f"- {rel_path}")

        if not file_entries:
            return ""

        return f"[This skill has supporting files in {skill_meta.name}/]:\n" + "\n".join(file_entries)

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

        self._active_skill = active_skill
        reset_loaded_skills()
        if active_skill:
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

            # Create a background task for cleanup to ensure zero blocking of the UI thread
            async def _background_cleanup(active_skills: list[str]) -> None:
                logger.info("_background_cleanup executing for skills: %s", active_skills)
                try:
                    await self._cleanup_session(query, chat_history, assistant_chunks, active_skills)
                except Exception as e:
                    logger.error("Background session cleanup failed: %s", e, exc_info=True)

            logger.info("Creating _background_cleanup task")
            task = asyncio.create_task(_background_cleanup(active_skills_list))
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
        from myrm_agent_harness.agent.observability.tool_call_broadcaster import (
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

    async def _prepare_context(self, context: dict[str, object]) -> dict[str, object]:
        """准备上下文(覆盖 BaseAgent)

        使用 ContextVar 传递不可序列化对象(storage_backend, memory_manager),
        避免 LangGraph checkpoint 序列化问题.
        """
        context = await super()._prepare_context(context)

        set_storage_backend(self.storage_backend)
        set_memory_manager(self.memory_manager)

        skill_paths = await self._get_skill_storage_paths()
        if skill_paths:
            context["skill_paths"] = skill_paths

        return context

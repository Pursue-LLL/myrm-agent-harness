"""SkillAgent tool building logic — meta-tools, planner, wiki tools.

[INPUT]
- meta_tools::get_meta_tools (POS: Meta-tools factory)
- tool_management::ToolRegistry (POS: Tool registration and resolution)
- sub_agents.planner (POS: Planner tool factory)
- toolkits.wiki (POS: Wiki tools)

[OUTPUT]
- SkillAgentToolsMixin: Mixin providing tool building methods for SkillAgent

[POS]
Tool building mixin for SkillAgent. Assembles meta-tools, planner tool,
wiki tools, and handles deferred tool registration via ToolRegistry.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.tool_management import ToolSnapshot, ToolSource
from myrm_agent_harness.toolkits.storage import storage_config
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.skills import SkillMetadata

logger = get_agent_logger(__name__)


class SkillAgentToolsMixin:
    """Mixin providing tool building methods for SkillAgent.

    Requires the following attributes from SkillAgent:
    - skill_backend, discovery_backend, write_backend
    - _embedding_config, skill_configs, _similarity_checker
    - _enable_file_tools, _enable_bash
    - _skill_env_map, _default_skill_instances, state_manager
    - storage_backend, llm, config
    - _wiki_base_dir, _wiki_search_fn
    - _tool_registry, user_tools, deferred_tools, user_middlewares
    """

    async def _build_tools(self) -> list[BaseTool]:
        """Build tool list via ToolRegistry."""
        from myrm_agent_harness.agent.streaming.utils import normalize_tool_names

        skills = await self._get_cached_skills()  # type: ignore[attr-defined]

        skill_env_map = dict(self._skill_env_map) if self._skill_env_map else {}  # type: ignore[attr-defined]
        if self.state_manager and self._default_skill_instances:  # type: ignore[attr-defined]
            for skill_name, instance_name in self._default_skill_instances.items():  # type: ignore[attr-defined]
                try:
                    instance = await self.state_manager.load_instance(  # type: ignore[attr-defined]
                        backend=self.skill_backend,  # type: ignore[attr-defined]
                        skill_name=skill_name,
                        instance_name=instance_name,
                    )
                    if instance:
                        skill_env_map[skill_name] = instance.config.env_overrides
                        logger.info("Loaded skill instance: %s.%s", skill_name, instance_name)
                except Exception as e:
                    logger.warning(
                        "Failed to load skill instance %s.%s: %s",
                        skill_name,
                        instance_name,
                        e,
                    )

        registry = self._tool_registry  # type: ignore[attr-defined]

        meta_tools = get_meta_tools(
            skills,
            self.skill_backend,  # type: ignore[attr-defined]
            discovery_backend=self.discovery_backend,  # type: ignore[attr-defined]
            write_backend=self.write_backend,  # type: ignore[attr-defined]
            embedding_config=self._embedding_config,  # type: ignore[attr-defined]
            skill_env_map=skill_env_map,
            skill_configs=self.skill_configs,  # type: ignore[attr-defined]
            similarity_checker=self._similarity_checker,  # type: ignore[attr-defined]
            registry=registry,
            enable_file_tools=self._enable_file_tools,  # type: ignore[attr-defined]
            enable_bash=self._enable_bash,  # type: ignore[attr-defined]
            enable_answer_tool=self._enable_answer_tool,  # type: ignore[attr-defined]
            available_tool_names=self._available_tool_names,  # type: ignore[attr-defined]
            available_tool_groups=self._available_tool_groups,  # type: ignore[attr-defined]
        )

        planner = self._create_planner_tool(skills)
        if planner is not None:
            meta_tools.append(planner)

        wiki_tools = self._create_wiki_tools()
        if wiki_tools:
            meta_tools.extend(wiki_tools)

        registry.register_many(meta_tools, source=ToolSource.META)
        registry.register_many(
            normalize_tool_names(self.user_tools),
            source=ToolSource.USER,  # type: ignore[attr-defined]
        )

        if self.deferred_tools:  # type: ignore[attr-defined]
            for tool in normalize_tool_names(self.deferred_tools):  # type: ignore[attr-defined]
                registry.register(tool, source=ToolSource.USER, deferred=True)

        # discover_capability_tool 由 get_meta_tools() 在 deferred 注册后创建，
        # 已包含框架级 deferred 工具索引。仅在用户传入 deferred_tools 且
        # discover 尚未注册时才补充创建（覆盖已有的以包含用户工具索引）。
        has_discover = registry.has_tool("discover_capability_tool")
        if self.deferred_tools and not has_discover:  # type: ignore[attr-defined]
            from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
                create_discover_capability_tool,
            )

            registry.register(
                create_discover_capability_tool(registry=registry),
                source=ToolSource.META,
            )

        all_middlewares: list[object] = list(self.user_middlewares)  # type: ignore[attr-defined]
        cached_mws = getattr(self, "_cached_middlewares", None)
        if cached_mws:
            seen_ids = {id(mw) for mw in all_middlewares}
            all_middlewares.extend(mw for mw in cached_mws if id(mw) not in seen_ids)

        for middleware in all_middlewares:
            if hasattr(middleware, "get_tools") and callable(middleware.get_tools):  # type: ignore[attr-defined]
                try:
                    mw_tools = middleware.get_tools()  # type: ignore[attr-defined]
                    if mw_tools:
                        for t in mw_tools:
                            is_internal = t.name.startswith("_")
                            registry.register(t, source=ToolSource.MIDDLEWARE, deferred=is_internal)  # type: ignore[arg-type]
                except Exception as e:
                    logger.warning(
                        "Failed to load tools from middleware %s: %s",
                        middleware.__class__.__name__,
                        e,
                    )

        self._tool_registry = registry  # type: ignore[attr-defined]
        resolved = registry.resolve()

        unattended = getattr(self.config, "unattended", False)  # type: ignore[attr-defined]
        if unattended:
            filtered = []
            for t in resolved:
                tags = getattr(t, "tags", []) or []
                if "interactive" in tags:
                    logger.info("Skipping interactive tool %s in unattended mode", getattr(t, "name", "unknown"))
                    continue
                filtered.append(t)
            resolved = filtered

        self._runtime_skill_count = len(skills)  # type: ignore[attr-defined]
        self._runtime_tool_count = len(resolved)  # type: ignore[attr-defined]

        logger.warning(
            "SkillAgent._build_tools resolved %d tools, %d skills: %s",
            len(resolved),
            len(skills),
            [t.name for t in resolved],
        )
        return resolved

    def _create_planner_tool(self, skills: list[SkillMetadata]) -> BaseTool | None:
        """Auto-create planner_tool if storage_backend is available and user hasn't provided one.

        Skips creation when there are no model-invocable skills.
        """
        if self.storage_backend is None:  # type: ignore[attr-defined]
            return None
        if any(
            getattr(t, "name", getattr(t, "tool_name", None)) == "planner_tool"
            for t in self.user_tools  # type: ignore[attr-defined]
        ):
            logger.info("planner_tool: user-provided override detected, skipping auto-creation")
            return None

        try:
            from myrm_agent_harness.agent.sub_agents.planner.archive import PlanArchiveStore, PlanRecaller
            from myrm_agent_harness.agent.sub_agents.planner.planner_agent_tools import create_planner_tool

            planner_config = getattr(self.config, "planner_config", None)  # type: ignore[attr-defined]
            max_chars = getattr(self.config, "max_skills_prompt_chars", 12000)  # type: ignore[attr-defined]

            available_skills: list[tuple[str, str]] = []
            current_chars = 0
            total_invocable = 0
            for s in skills:
                if not s.model_invocable:
                    continue
                total_invocable += 1
                est_chars = len(s.name) + len(s.description)
                if current_chars + est_chars > max_chars:
                    if not any(x[0] == "..." for x in available_skills):
                        available_skills.append(
                            (
                                "...",
                                f"... truncated. {total_invocable}+ skills loaded, "
                                "use skill_search tool to find unlisted skills.",
                            )
                        )
                    continue
                available_skills.append((s.name, s.description))
                current_chars += est_chars

            if total_invocable == 0:
                logger.info("planner_tool: skipped (0 model-invocable skills)")
                return None

            # Initialize Plan Archive & Recall (Workflow RAG)
            archive_store = None
            recaller = None
            try:
                db_path = storage_config.get_local_base_path() / "plan_archive.db"
                mm = getattr(self, "memory_manager", None)
                vector = getattr(mm, "_vector", None) if mm else None
                embedding = getattr(mm, "_embedding", None) if mm else None
                archive_store = PlanArchiveStore(db_path, vector_store=vector, embedding=embedding)
                recaller = PlanRecaller(archive_store)
            except Exception as e:
                logger.warning("Plan archive initialization failed (proceeding without): %s", e)

            tool = create_planner_tool(
                self.llm,  # type: ignore[attr-defined]
                self.storage_backend,  # type: ignore[attr-defined]
                planner_config=planner_config,
                available_skills=available_skills or None,
                plan_archive_store=archive_store,
                plan_recaller=recaller,
            )
            logger.warning(
                " planner_tool auto-created (skills=%d, truncated=%s)",
                len(available_skills),
                current_chars > max_chars,
            )
            return tool
        except Exception as e:
            logger.warning("planner_tool auto-creation failed: %s", e)
            return None

    def _create_wiki_tools(self) -> list[BaseTool]:
        """Auto-create wiki tools if wiki_base_dir is configured.

        Creates 4 LangChain tools: wiki_ingest, wiki_compile, wiki_query, wiki_maintain.
        """
        if self._wiki_base_dir is None:  # type: ignore[attr-defined]
            return []

        try:
            from myrm_agent_harness.toolkits.wiki import (
                WikiCompiler,
                WikiConfig,
                WikiLinter,
                WikiQueryEngine,
                WikiStructure,
                create_wiki_tools,
            )

            structure = WikiStructure(self._wiki_base_dir)  # type: ignore[attr-defined]
            structure.ensure_structure()
            config = WikiConfig()
            compiler = WikiCompiler(self.llm, structure, config)  # type: ignore[attr-defined]
            query_engine = WikiQueryEngine(
                self.llm,  # type: ignore[attr-defined]
                structure,
                config,
                search_fn=self._wiki_search_fn,  # type: ignore[attr-defined]
            )
            linter = WikiLinter(self.llm, structure, config)  # type: ignore[attr-defined]

            self._wiki_structure = structure  # type: ignore[attr-defined]
            self._wiki_compiler = compiler  # type: ignore[attr-defined]

            tools = create_wiki_tools(compiler, query_engine, linter, structure)

            self._register_large_doc_ingest(structure, compiler)

            logger.info(
                " wiki tools auto-created (4 tools, base_dir=%s)",
                self._wiki_base_dir,  # type: ignore[attr-defined]
            )
            return tools
        except Exception as e:
            logger.warning("wiki tools creation failed: %s", e)
            return []

    @staticmethod
    def _register_large_doc_ingest(
        structure: "WikiStructure",  # noqa: F821
        compiler: "WikiCompiler",  # noqa: F821
    ) -> None:
        """Register the PDF large-doc auto-ingest callback into wiki knowledge base.

        When pdf_reader detects a document exceeding RAG_PAGE_THRESHOLD pages,
        it calls this callback to asynchronously ingest the full text into the
        wiki for subsequent RAG retrieval via wiki_query.
        """
        from myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader import (
            register_large_doc_ingest_callback,
        )

        async def _ingest_large_doc(filename: str, full_text: str, doc_hash: str) -> None:
            raw_path = structure.get_raw_file_path(f"auto_rag_{doc_hash}_{filename}.md")
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            content = f"# {filename}\n\n{full_text}"
            try:
                fd = os.open(str(raw_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, content.encode("utf-8"))
                os.close(fd)
            except FileExistsError:
                logger.debug("Large doc already ingested: %s", filename)
                return

            compiler.enqueue_file(raw_path)
            logger.info("Large doc auto-ingested into wiki for RAG: %s (%s)", filename, doc_hash)

        register_large_doc_ingest_callback(_ingest_large_doc)

    def get_tool_snapshot(self) -> list[ToolSnapshot]:
        """Return a serializable snapshot of the current tool set."""
        registry = getattr(self, "_tool_registry", None)
        if registry is None:
            return []
        return registry.snapshot()

    async def _get_skill_storage_paths(self) -> list[str]:
        """Get all skill storage paths (absolute)."""
        skills = await self._get_cached_skills()  # type: ignore[attr-defined]
        base_path = storage_config.get_local_base_path()
        return [str(base_path / skill.storage_path) for skill in skills if skill.storage_path]

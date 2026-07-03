"""SkillAgent tool building logic — meta-tools, todo progress, wiki tools.

[INPUT]
- meta_tools::get_meta_tools (POS: Meta-tools factory)
- tool_management::ToolRegistry (POS: Tool registration and resolution)
- agent.meta_tools.progress (POS: Main-agent todo_write factory)
- toolkits.wiki (POS: Wiki tools)

[OUTPUT]
- SkillAgentToolsMixin: Mixin providing tool building methods for SkillAgent

[POS]
Tool building mixin for SkillAgent. Assembles meta-tools, todo_write (when
enable_planning or workspace todos exist), wiki tools, and deferred tool registration.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.tool_management import ToolBindMode, ToolSnapshot, ToolSource
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
    - _task_workspace_root (chat sandbox path for progress persistence)
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

        todo_tool = await self._create_todo_write_tool()
        if todo_tool is not None:
            meta_tools.append(todo_tool)

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
                registry.register(tool, source=ToolSource.USER, bind_mode=ToolBindMode.DISCOVERABLE)

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
                            bind_mode = ToolBindMode.RUNTIME_ONLY if is_internal else ToolBindMode.TURN1
                            registry.register(t, source=ToolSource.MIDDLEWARE, bind_mode=bind_mode)  # type: ignore[arg-type]
                except Exception as e:
                    logger.warning(
                        "Failed to load tools from middleware %s: %s",
                        middleware.__class__.__name__,
                        e,
                    )

        from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
            sync_discover_capability_tool,
        )

        sync_discover_capability_tool(
            registry,
            skills=skills,
            embedding_config=self._embedding_config,  # type: ignore[attr-defined]
            embedding_cache=getattr(self, "_embedding_cache", None),
            active_tool_groups=self._available_tool_groups,  # type: ignore[attr-defined]
            bound_skill_names=frozenset(s.name for s in skills),
            library_skill_names=self._library_skill_names,  # type: ignore[attr-defined]
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

    async def _workspace_has_todos(self) -> bool:
        """Return True when persisted todos exist in the chat workspace."""
        if self.storage_backend is None:  # type: ignore[attr-defined]
            return False
        try:
            from myrm_agent_harness.agent.meta_tools.progress.storage import workspace_todos_exist

            return await workspace_todos_exist(
                self.storage_backend,  # type: ignore[attr-defined]
                workspace_root=self._resolve_task_workspace_root(),
            )
        except Exception as e:
            logger.warning("Failed to check workspace todos existence: %s", e)
            return False

    async def _should_load_todo_write_tool(self) -> bool:
        """todo_write loads when planning is enabled or when resuming existing todos."""
        if self._enable_planning:  # type: ignore[attr-defined]
            return True
        if await self._workspace_has_todos():
            logger.info("todo_write: loading for existing workspace todos (resume)")
            return True
        return False

    def _resolve_task_workspace_root(self) -> str | None:
        """Resolve chat workspace for progress persistence."""
        from myrm_agent_harness.agent.middlewares._session_context import get_workspace_root

        live_root = get_workspace_root()
        if live_root:
            return live_root
        bound_root = getattr(self, "_task_workspace_root", None)  # type: ignore[attr-defined]
        if isinstance(bound_root, str) and bound_root.strip():
            return bound_root.strip()
        return None

    async def _create_todo_write_tool(self) -> BaseTool | None:
        """Auto-create todo_write when planning is enabled or workspace has todos."""
        if not await self._should_load_todo_write_tool():
            logger.info("todo_write: skipped (planning disabled, no existing todos)")
            return None
        if any(
            getattr(t, "name", getattr(t, "tool_name", None)) == "todo_write"
            for t in self.user_tools  # type: ignore[attr-defined]
        ):
            logger.info("todo_write: user-provided override detected, skipping auto-creation")
            return None

        try:
            from myrm_agent_harness.agent.meta_tools.progress.todo_write_tool import create_todo_write_tool

            tool = create_todo_write_tool(workspace_root=self._resolve_task_workspace_root())
            logger.warning(" todo_write auto-created")
            return tool
        except Exception as e:
            logger.warning("todo_write auto-creation failed: %s", e)
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

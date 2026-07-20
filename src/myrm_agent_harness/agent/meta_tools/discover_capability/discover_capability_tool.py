"""统一能力发现元工具 (Unified Capability Discovery)

[INPUT]
- backends.skills.types::SkillMetadata (POS: 技能元数据定义)
- langchain.tools::tool (POS: LangChain 工具装饰器)
- pydantic::BaseModel, Field (POS: 参数验证)
- .engine::SkillSearchEngine (POS: BM25/Regex 搜索引擎)
- .hybrid_engine::HybridSkillSearchEngine (POS: 混合搜索引擎, 可选)
- toolkits.retriever.embedding.factory::EmbeddingConfig (POS: Embedding 配置, 可选)
- toolkits.memory.protocols.cache::EmbeddingCacheProtocol (POS: Embedding 缓存协议, 可选)
- agent.tool_management.registry::ToolRegistry (POS: 工具注册表)

[OUTPUT]
- create_discover_capability_tool: 创建统一能力发现工具的工厂函数
- sync_discover_capability_tool: 注册 discover_capability_tool（当有可搜索技能时）

[POS]
Unified Capability Discovery meta-tool. Indexes external skills (MCP PTC + user skills)
via SkillSearchEngine into a semantic search index. Capability gap detection provides
hints when tools/skills are disabled or not installed.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Literal

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.memory.protocols.cache import (
        EmbeddingCacheProtocol,
    )
    from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig


def create_discover_capability_tool(
    registry: ToolRegistry | None = None,
    skills: list[SkillMetadata] | None = None,
    embedding_config: EmbeddingConfig | None = None,
    cache: EmbeddingCacheProtocol | None = None,
    active_tool_groups: frozenset[str] | None = None,
    bound_skill_names: frozenset[str] | None = None,
    library_skill_names: frozenset[str] | None = None,
) -> BaseTool:
    """创建统一能力发现工具

    Args:
        registry: 工具注册表 (reserved for future use)
        skills: 全部可用技能列表 (用于构建外部技能搜索索引)
        embedding_config: Embedding 模型配置(可选)
        cache: Embedding 缓存实例(可选)

    Returns:
        discover_capability 工具函数
    """
    skills = skills or []
    all_skills = list(skills)

    if embedding_config is not None and all_skills:
        from myrm_agent_harness.agent.meta_tools.skills.search.hybrid_engine import (
            HybridSkillSearchEngine,
        )

        engine = HybridSkillSearchEngine(all_skills, embedding_config, embedding_cache=cache)
    elif all_skills:
        from myrm_agent_harness.agent.meta_tools.skills.search.engine import (
            SkillSearchEngine,
        )

        engine = SkillSearchEngine(all_skills)
    else:
        engine = None

    tool_description = """Search for missing capabilities among skills already available to this agent (bound library + MCP PTC skills).
NOT for installing new skills from external markets — use `skill_discovery_tool` for that.

IMPORTANT: You MUST search here BEFORE declining any user request due to missing capability. Never tell the user you cannot do something without first checking if a skill exists (e.g., drawing, video generation, Github, Jira, etc.).

**How to query**:
- Query naturally in any language.
- For best results across languages, use format: "concept/translation/synonym" (e.g., "火车票/railway ticket/train booking").
- Use query="*" to list all available external skills.

**What happens next**:
- If an **External Skill** is found, you MUST use `skill_select_tool` to load its SOP documentation before using it.

**Examples**: video generation, GitHub integration, database operations.
"""

    active_groups = active_tool_groups or frozenset()
    bound_names = bound_skill_names or frozenset()
    library_names = library_skill_names or frozenset()

    def _resolve_gap_hints(search_query: str, base_message: str) -> str:
        from myrm_agent_harness.agent.meta_tools.discover_capability.capability_gap import (
            detect_capability_gap,
            detect_skill_gap,
            format_capability_gap_block,
            format_skill_gap_block,
        )

        parts = [base_message]
        cap_gap = detect_capability_gap(search_query, active_groups)
        if cap_gap is not None:
            parts.append(format_capability_gap_block(cap_gap))
        skill_gap = detect_skill_gap(search_query, bound_names, library_names)
        if skill_gap is not None:
            parts.append(format_skill_gap_block(skill_gap))
        return "\n\n".join(parts)

    async def _emit_gap_events(search_query: str) -> None:
        from myrm_agent_harness.agent.meta_tools.discover_capability.capability_gap import (
            detect_capability_gap,
            detect_skill_gap,
        )
        from myrm_agent_harness.utils.event_utils import dispatch_custom_event

        cap_gap = detect_capability_gap(search_query, active_groups)
        if cap_gap is not None:
            await dispatch_custom_event(
                "capability_gap",
                {"tool_id": cap_gap.tool_id, "tool_group": cap_gap.tool_group},
            )
        skill_gap = detect_skill_gap(search_query, bound_names, library_names)
        if skill_gap is not None:
            await dispatch_custom_event("skill_gap", {"skill_id": skill_gap.skill_id})

    class DiscoverCapabilityInput(BaseModel):
        query: str = Field(
            description=(
                "Search query (any language). "
                "Use 'concept/translation/synonym' format for best results. "
                "Use '*' to list all skills."
            )
        )
        mode: Literal["bm25", "regex"] = Field(
            default="bm25",
            description="Search mode: 'bm25' for natural language, 'regex' for pattern matching",
        )

    @tool(
        "discover_capability_tool",
        description=tool_description,
        args_schema=DiscoverCapabilityInput,
    )
    async def discover_capability_func(query: str, mode: Literal["bm25", "regex"] = "bm25") -> str:
        """Search for capabilities across native tools and external skills."""
        not_found = f"No capabilities found matching '{query}'. Try broader terms or synonyms."

        if engine is None:
            message = _resolve_gap_hints(query, not_found)
            await _emit_gap_events(query)
            return message

        if mode == "regex":
            matches = engine.search_regex(query)
        else:
            matches = engine.search_bm25(query, top_k=10)

        if inspect.isawaitable(matches):
            matches = await matches

        if not matches:
            message = _resolve_gap_hints(query, not_found)
            await _emit_gap_events(query)
            return message

        skill_text = "\n".join(f"- **{s.name}**: {s.description}" for s in matches)
        result_body = (
            "### Found Skills (You MUST use `skill_select_tool` to load their SOPs before using):\n"
            f"<ExternalSkills>\n{skill_text}\n</ExternalSkills>"
        )

        await _emit_gap_events(query)
        return _resolve_gap_hints(query, result_body)

    return discover_capability_func


def sync_discover_capability_tool(
    registry: ToolRegistry,
    *,
    skills: list[SkillMetadata] | None = None,
    embedding_config: EmbeddingConfig | None = None,
    embedding_cache: EmbeddingCacheProtocol | None = None,
    active_tool_groups: frozenset[str] | None = None,
    bound_skill_names: frozenset[str] | None = None,
    library_skill_names: frozenset[str] | None = None,
) -> BaseTool | None:
    """Register discover_capability_tool when searchable skills exist.

    Must run after all tools (framework + server) are registered.
    """
    from myrm_agent_harness.agent.tool_management.registry import ToolSource

    discoverable_skills = [s for s in (skills or []) if s.model_invocable]

    registry.remove_tool("discover_capability_tool")

    if not discoverable_skills:
        return None

    tool = create_discover_capability_tool(
        registry=registry,
        skills=discoverable_skills,
        embedding_config=embedding_config,
        cache=embedding_cache,
        active_tool_groups=active_tool_groups,
        bound_skill_names=bound_skill_names,
        library_skill_names=library_skill_names,
    )
    registry.register(tool, source=ToolSource.META)
    return tool

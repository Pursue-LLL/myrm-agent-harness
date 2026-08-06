"""统一能力发现元工具 (Unified Capability Discovery)

[INPUT]
- backends.skills.types::SkillMetadata (POS: 技能元数据定义)
- langchain.tools::tool (POS: LangChain 工具装饰器)
- pydantic::BaseModel, Field (POS: 参数验证)
- .engine::SkillSearchEngine (POS: BM25/Regex 搜索引擎)
- .hybrid_engine::HybridSkillSearchEngine (POS: 混合搜索引擎, 可选)
- toolkits.retriever.embedding.factory::EmbeddingConfig (POS: Embedding 配置, 可选)
- toolkits.memory.protocols.cache::EmbeddingCacheProtocol (POS: Embedding 缓存协议, 可选)
- agent.tool_management.registry::ToolRegistry (POS: 工具注册表，由 sync_discover_capability_tool 使用)

[OUTPUT]
- create_discover_capability_tool: 创建统一能力发现工具的工厂函数
- sync_discover_capability_tool: 条件注册 skill_search_tool（hidden_skill_count > 0 时）
- 运行时命中结果以 `<BoundSkills>` XML 包裹

[POS]
Unified Capability Discovery meta-tool. Indexes agent-bound searchable skills (MCP PTC + user skills)
via SkillSearchEngine into a semantic search index.
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

_MARKET_INSTALLED_LINE = (
    "NOT for installing new skills from external markets — use `skill_market_tool` for that."
)
_MARKET_OFF_LINE = (
    "NOT for installing new skills from external markets. "
    "Install skills via product Settings → Skills → Discover, "
    "or enable the Skill Market capability on this agent profile."
)


def _build_tool_description(*, market_tool_mounted: bool) -> str:
    market_line = _MARKET_INSTALLED_LINE if market_tool_mounted else _MARKET_OFF_LINE
    return f"""Search for missing capabilities among skills already available to this agent (bound library + MCP PTC skills).
{market_line}

IMPORTANT: You MUST search here BEFORE declining any user request due to missing capability. Never tell the user you cannot do something without first checking if a skill exists (e.g., drawing, video generation, Github, Jira, etc.).

**How to query**:
- Query naturally in any language.
- For best results across languages, use format: "concept/translation/synonym" (e.g., "火车票/railway ticket/train booking").
- Use query="*" to list all searchable skills bound to this agent.

**What happens next**:
- If a **skill** is found, you MUST use `skill_select_tool` to load its SOP documentation before using it.

**Examples**: video generation, GitHub integration, database operations.
"""


def create_discover_capability_tool(
    skills: list[SkillMetadata] | None = None,
    embedding_config: EmbeddingConfig | None = None,
    cache: EmbeddingCacheProtocol | None = None,
    *,
    market_tool_mounted: bool = False,
) -> BaseTool:
    """创建统一能力发现工具

    Args:
        skills: 全部可用技能列表 (用于构建 agent 已绑定技能搜索索引)
        embedding_config: Embedding 模型配置(可选)
        cache: Embedding 缓存实例(可选)
        market_tool_mounted: Whether skill_market_tool is Turn1-mounted on this agent.

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

    tool_description = _build_tool_description(market_tool_mounted=market_tool_mounted)

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
        "skill_search_tool",
        description=tool_description,
        args_schema=DiscoverCapabilityInput,
    )
    async def discover_capability_func(query: str, mode: Literal["bm25", "regex"] = "bm25") -> str:
        """Search for capabilities among skills bound to this agent."""
        not_found = f"No capabilities found matching '{query}'. Try broader terms or synonyms."

        if engine is None:
            return not_found

        if mode == "regex":
            matches = engine.search_regex(query)
        else:
            matches = engine.search_bm25(query, top_k=10)

        if inspect.isawaitable(matches):
            matches = await matches

        if not matches:
            return not_found

        skill_text = "\n".join(f"- **{s.name}**: {s.description}" for s in matches)
        return (
            "### Found bound skills (You MUST use `skill_select_tool` to load their SOPs before using):\n"
            f"<BoundSkills>\n{skill_text}\n</BoundSkills>"
        )

    return discover_capability_func


def sync_discover_capability_tool(
    registry: ToolRegistry,
    *,
    skills: list[SkillMetadata] | None = None,
    skill_configs: dict[str, dict[str, object]] | None = None,
    available_tool_names: frozenset[str] | None = None,
    available_tool_groups: frozenset[str] | None = None,
    embedding_config: EmbeddingConfig | None = None,
    embedding_cache: EmbeddingCacheProtocol | None = None,
) -> BaseTool | None:
    """Register skill_search_tool when inline catalog has hidden bound skills.

    Must run after all tools (framework + server) are registered.
    Uses the same catalog resolution as ``ensure_skill_catalog_in_messages``.
    """
    from myrm_agent_harness.agent.skills.runtime.catalog_display import (
        resolve_catalog_display_skills,
        should_mount_skill_search_tool,
    )
    from myrm_agent_harness.agent.tool_management.registry import ToolSource

    bound_skills = skills or []
    registry.remove_tool("skill_search_tool")

    if not should_mount_skill_search_tool(
        bound_skills,
        skill_configs=skill_configs,
        available_tool_names=available_tool_names,
        available_tool_groups=available_tool_groups,
    ):
        return None

    resolution = resolve_catalog_display_skills(
        bound_skills,
        skill_configs=skill_configs,
        available_tool_names=available_tool_names,
        available_tool_groups=available_tool_groups,
    )
    discoverable_skills = [s for s in resolution.filtered_skills if s.model_invocable]
    if not discoverable_skills:
        return None

    market_tool_mounted = registry.has_tool("skill_market_tool")

    tool = create_discover_capability_tool(
        skills=discoverable_skills,
        embedding_config=embedding_config,
        cache=embedding_cache,
        market_tool_mounted=market_tool_mounted,
    )
    registry.register(tool, source=ToolSource.META)
    return tool

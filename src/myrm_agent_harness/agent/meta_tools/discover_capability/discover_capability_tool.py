"""统一能力发现元工具 (Unified Capability Discovery)

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- backends.skills.types::SkillMetadata (POS: 技能元数据定义)
- langchain.tools::tool (POS: LangChain 工具装饰器)
- pydantic::BaseModel, Field (POS: 参数验证)
- .engine::SkillSearchEngine (POS: BM25/Regex 搜索引擎)
- .hybrid_engine::HybridSkillSearchEngine (POS: 混合搜索引擎, 可选)
- toolkits.retriever.embedding.factory::EmbeddingConfig (POS: Embedding 配置, 可选)
- toolkits.memory.protocols.cache::EmbeddingCacheProtocol (POS: Embedding 缓存协议, 可选)
- agent.tool_management.registry::ToolRegistry (POS: 原生工具注册表)

[OUTPUT]
- create_discover_capability_tool: 创建统一能力发现工具的工厂函数

[POS]
Unified Capability Discovery meta-tool. Facade pattern that unifies native deferred tools (ToolRegistry) and external skills (SkillSearchEngine) into a single semantic index with XML-based robust middleware interception.
"""

from __future__ import annotations

import inspect
import json
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
) -> BaseTool:
    """创建统一能力发现工具

    Args:
        registry: 原生工具注册表 (用于搜索 Deferred Native Tools)
        skills: 全部可用技能列表 (用于构建外部技能搜索索引)
        embedding_config: Embedding 模型配置(可选)
        cache: Embedding 缓存实例(可选)

    Returns:
        discover_capability 工具函数
    """
    skills = skills or []

    # 1. Prepare Native Tools as SkillMetadata for unified indexing
    native_tool_map = {}
    native_skills = []
    if registry is not None:
        from myrm_agent_harness.backends.skills.types import SkillMetadata

        for t in registry.get_deferred_tools():
            native_tool_map[t.name] = t
            native_skills.append(
                SkillMetadata(
                    name=t.name,
                    description=t.description or "",
                )
            )

    all_skills = skills + native_skills

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

    tool_description = """Search for missing capabilities (both internal native tools and external skills/plugins).
IMPORTANT: You MUST search here BEFORE declining any user request due to missing capability. Never tell the user you cannot do something without first checking if a skill or tool exists (e.g., drawing, video generation, cron jobs, Github, Jira, etc.).

**How to query**:
- Query naturally in any language.
- For best results across languages, use format: "concept/translation/synonym" (e.g., "火车票/railway ticket/train booking").
- Use query="*" to list all available external skills.

**What happens next**:
- If a **Native Tool** is found, the system will automatically mount it for you, and you can use it in the NEXT turn.
- If an **External Skill** is found, you MUST use `skill_select_tool` to load its SOP documentation before using it.

**Examples**: cron jobs, video generation, stale skill cleanup (`skill_analyze_tool`), bash process management.
"""

    if native_skills:
        deferred_names = ", ".join(s.name for s in native_skills[:20])
        tool_description += f"\n**Discoverable native tools**: {deferred_names}\n"

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
        if engine is None:
            return f"No capabilities found matching '{query}'. Try broader terms or synonyms."

        # Perform ONE unified semantic search.
        # HybridSkillSearchEngine returns coroutines; SkillSearchEngine returns lists.
        if mode == "regex":
            matches = engine.search_regex(query)
        else:
            matches = engine.search_bm25(query, top_k=10)

        if inspect.isawaitable(matches):
            matches = await matches

        if not matches:
            return f"No capabilities found matching '{query}'. Try broader terms or synonyms."

        native_matches = []
        external_matches = []

        # Split results back into native and external
        for m in matches:
            if m.name in native_tool_map:
                t = native_tool_map[m.name]
                schema = getattr(t, "args_schema", None)
                schema_dict = schema.model_json_schema() if schema else {}
                native_matches.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "schema": schema_dict,
                    }
                )
            else:
                external_matches.append(m)

        results = []

        if native_matches:
            # We output JSON array for native matches wrapped in XML tags for robust parsing
            native_json = json.dumps(native_matches, ensure_ascii=False, indent=2)
            results.append(
                f"###  Found Native Tools (System will AUTO-MOUNT these for the next turn):\n"
                f"<AutoMountTools>\n{native_json}\n</AutoMountTools>"
            )

        if external_matches:
            skill_text = "\n".join(f"- **{s.name}**: {s.description}" for s in external_matches)
            results.append(
                f"###  Found External Skills (You MUST use `skill_select_tool` to load their SOPs before using):\n"
                f"<ExternalSkills>\n{skill_text}\n</ExternalSkills>"
            )

        return "\n\n".join(results)

    return discover_capability_func

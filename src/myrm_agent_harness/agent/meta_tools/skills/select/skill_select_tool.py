"""选择技能元工具

[INPUT]
- backends.skills.protocols::SkillBackend (POS: 技能后端协议，提供技能加载能力)
- backends.skills.types::SkillMetadata, SkillInstance (POS: 技能元数据与实例)
- skill_document_loader (POS: SOP 加载与 L2 文件读取)

[OUTPUT]
- build_skill_select_static_description: byte-stable tool description (no bound catalog)
- create_select_skill_tool: 创建技能选择工具的工厂函数（skill_search 提示经 with_dynamic_hints 条件注入）

[POS]
Skill selection meta-tool. Enables the model to select a skill and load its SOP documentation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.backends.skills.protocols import SkillBackend

from myrm_agent_harness.agent.meta_tools.skills.select.skill_document_loader import (
    build_reload_summary_with_index,
    get_skill_document,
    get_skill_file,
)
from myrm_agent_harness.backends.skills.types import SkillInstance, SkillMetadata

logger = logging.getLogger(__name__)

__all__ = [
    "build_skill_select_static_description",
    "create_select_skill_tool",
    "get_skill_document",
]


def build_skill_select_static_description() -> str:
    """Static skill_select_tool description (catalog lives in HumanMessage)."""
    return """Select bound skills and load their SOP documentation.

The bound skill catalog is in the <bound_skills> block at the start of the first user message in this conversation.
Rules:
1. Select skills listed in that <bound_skills> catalog → read and follow the returned SOP.
2. Select each skill only ONCE — it stays available for the entire conversation (even after resume). Do NOT re-select; use skill_select_tool(file_path=...) for auxiliary files under scripts/, references/, templates/, or assets/, then bash_code_execute_tool to run.
3. You may select multiple skills if they help solve the user's problem.
4. Skills with available="false" cannot be loaded — skip them.
5. Do NOT confuse tools (_tool suffix, callable) with skills (_skill suffix, select via this tool only).
6. When the user's message starts with [use <skill_name>], you MUST immediately select that skill."""


_SKILL_SEARCH_HINTS: dict[str, str] = {
    "skill_search_tool": (
        "If `<bound_skills>` includes hidden_count, use skill_search_tool first to find unlisted bound skills. "
        "Skills not listed in <bound_skills> are still available — search with skill_search_tool first, then select."
    ),
}


def create_select_skill_tool(
    skills: list[SkillMetadata],
    skill_backend: SkillBackend,
    skill_instances: dict[str, SkillInstance] | None = None,
) -> BaseTool:
    """Create the skill-select meta-tool."""
    tool_description = build_skill_select_static_description()

    class SelectSkillInput(BaseModel):
        skill_names: list[str] = Field(
            description="Skill names from the <bound_skills> catalog (must end with _skill). One or more allowed.",
            min_length=1,
        )
        reason: str = Field(description="Brief reason for selecting these skills (required, max 100 chars)")
        file_path: str | None = Field(
            default=None,
            description="Optional path to a specific file within the skill (e.g. 'scripts/setup.py', 'references/api.md'). "
            "Only allowed subdirs: scripts/, references/, templates/, assets/.",
        )

    @tool("skill_select_tool", description=tool_description, args_schema=SelectSkillInput)
    async def select_skill_func(skill_names: list[str], reason: str, file_path: str | None = None) -> str:
        """Select skills and load their SOP documentation or specific auxiliary files."""
        from myrm_agent_harness.agent.skill_agent.context import (
            add_loaded_skill,
            get_loaded_skills,
        )
        from myrm_agent_harness.backends.skills.usage_recorder import (
            record_skill_selection,
        )

        available_names = [s.name for s in skills]
        loaded_names = {s.name for s in get_loaded_skills()}
        selected_skills_info = []

        for skill_name in skill_names:
            skill_meta = next((s for s in skills if s.name == skill_name), None)
            if not skill_meta:
                hint = ", ".join(available_names[:15])
                selected_skills_info.append(f"\nError: skill '{skill_name}' not found. Available: [{hint}]")
                continue

            if file_path:
                file_content = await get_skill_file(skill_meta, skill_backend, file_path)
                if file_content is not None:
                    selected_skills_info.append(file_content)
                    record_skill_selection(skill_meta, success=True)
                else:
                    selected_skills_info.append(
                        f"# {skill_name}\n\nError: file '{file_path}' not found or inaccessible"
                    )
                    record_skill_selection(skill_meta, success=False)
            elif skill_name in loaded_names:
                selected_skills_info.append(await build_reload_summary_with_index(skill_meta, skill_backend))
            else:
                instance = skill_instances.get(skill_name) if skill_instances else None
                skill_doc = await get_skill_document(skill_meta, skill_backend, skill_instance=instance)
                if skill_doc:
                    selected_skills_info.append(skill_doc)
                    add_loaded_skill(skill_meta)
                    record_skill_selection(skill_meta, success=True)
                else:
                    selected_skills_info.append(f"# {skill_name}\n\nError: failed to load skill document")
                    record_skill_selection(skill_meta, success=False)

        skill_docs_formatted: list[str] = []
        for idx, skill_name in enumerate(skill_names):
            if idx < len(selected_skills_info):
                skill_docs_formatted.append(f"{skill_name}：{selected_skills_info[idx]}")

        return f"<skills_sop>\n{chr(10).join(skill_docs_formatted)}\n</skills_sop>"

    from myrm_agent_harness.utils.tool_dynamic_hints import with_dynamic_hints

    return with_dynamic_hints(select_skill_func, _SKILL_SEARCH_HINTS)

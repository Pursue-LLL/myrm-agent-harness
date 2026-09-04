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
from myrm_agent_harness.utils.locale import is_chinese

logger = logging.getLogger(__name__)

__all__ = [
    "build_skill_select_static_description",
    "create_select_skill_tool",
    "get_skill_document",
]


_SKILL_SELECT_TOOL_DESCRIPTION_ZH = """选择已绑定的技能并加载其 SOP 文档。

已绑定技能目录位于本会话首条用户消息开头的 <bound_skills> 块中。
规则：
1. 选择 <bound_skills> 目录中列出的技能 → 阅读并严格遵循返回的 SOP 文档。
2. 每个技能在当前会话只需选择一次 — 加载后的 SOP 在后续对话中持续有效。切勿重复加载技能；如需读取辅助脚本或参考文档，使用 skill_select_tool(file_path=...)（仅限 scripts/、references/、templates/、assets/ 目录），随后使用 bash_code_execute_tool 执行。
3. 如有助于解决用户问题，可同时选择多个技能。
4. available="false" 的技能无法加载 — 自动跳过。
5. 切勿混淆工具（_tool 后缀，可直接调用）与技能（_skill 后缀，仅能通过本工具选择加载）。
6. 当用户消息以 [use <skill_name>] 开头时，必须立即选择该技能。"""

_SKILL_SELECT_TOOL_DESCRIPTION_EN = """Select bound skills and load their SOP documentation.

The bound skill catalog is in the <bound_skills> block at the start of the first user message in this conversation.
Rules:
1. Select skills listed in that <bound_skills> catalog → read and follow the returned SOP.
2. Select each skill only ONCE per conversation — its SOP remains active for all subsequent turns. Do NOT re-select; use skill_select_tool(file_path=...) for auxiliary files under scripts/, references/, templates/, or assets/, then execute via bash_code_execute_tool.
3. You may select multiple skills if they help solve the user's problem.
4. Skills with available="false" cannot be loaded — skip them.
5. Do NOT confuse tools (_tool suffix, callable) with skills (_skill suffix, select via this tool only).
6. When the user's message starts with [use <skill_name>], you MUST immediately select that skill."""


def build_skill_select_static_description(locale: str | None = None) -> str:
    """Static skill_select_tool description (catalog lives in HumanMessage)."""
    if is_chinese(locale):
        return _SKILL_SELECT_TOOL_DESCRIPTION_ZH
    return _SKILL_SELECT_TOOL_DESCRIPTION_EN


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
    *,
    locale: str | None = None,
) -> BaseTool:
    """Create the skill-select meta-tool."""
    tool_description = build_skill_select_static_description(locale)

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

        skill_entries: list[str] = []
        for idx, skill_name in enumerate(skill_names):
            if idx >= len(selected_skills_info):
                continue
            info = selected_skills_info[idx]
            is_err = (
                info.lstrip().startswith("Error:")
                or f"Error: skill '{skill_name}'" in info
                or "Error: failed to load" in info
                or "Error: file '" in info
            )
            status = "error" if is_err else "ready"
            safe_info = (
                info.replace("</skill_entry>", "&lt;/skill_entry&gt;")
                .replace("</skills_sop>", "&lt;/skills_sop&gt;")
            )
            skill_entries.append(
                f'<skill_entry name="{skill_name}" status="{status}">\n{skill_name}：{safe_info}\n</skill_entry>'
            )

        return f"<skills_sop>\n{chr(10).join(skill_entries)}\n</skills_sop>"

    from myrm_agent_harness.utils.tool_dynamic_hints import with_dynamic_hints

    return with_dynamic_hints(select_skill_func, _SKILL_SEARCH_HINTS)

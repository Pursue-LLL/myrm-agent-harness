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


_SKILL_SELECT_TOOL_DESCRIPTION_ZH = """选择并激活已绑定的技能，以获得专业领域能力、外部服务集成或任务标准流程（SOP）。

已绑定技能目录位于本会话首条用户消息开头的 <bound_skills> 块中。
规则：
1. 强制要求：若用户请求涉及 <bound_skills> 中列出的任何专属领域、外部数据/服务或业务流程，你必须在第 1 轮首先调用本工具选择对应技能，严禁在未加载技能的情况下臆断、凭空猜测或声称无法完成。
2. 每个技能在当前会话只需选择一次 — 加载后的 SOP 及能力在后续对话中持续有效，切勿重复选择已加载的技能。
3. 若有助于解决问题，可同时选择多个技能。
4. 如需读取已加载技能的辅助脚本或参考文档，可传入 file_path 参数（例如 'scripts/run.py'、'references/api.md'）。
5. 切勿混淆基础工具（_tool 后缀，可直接调用）与专业技能（_skill 后缀，必须通过本工具先选择加载）。
6. 当用户消息以 [use <skill_name>] 开头或明确提及技能名称时，必须立即选择该技能。"""

_SKILL_SELECT_TOOL_DESCRIPTION_EN = """Select and activate bound skills that provide specialized domain capabilities, external service integrations, or task SOPs.

The bound skill catalog is listed in the <bound_skills> block at the start of the first user message in this conversation.
Rules:
1. MANDATORY: If the user request relates to any specialized domain, external data/service, or specific workflow in <bound_skills>, you MUST select the corresponding skill on turn 1 BEFORE taking any other action. Never guess, hallucinate, or claim inability without loading the skill.
2. Select each skill only ONCE per conversation — its SOP and capabilities remain active for all subsequent turns. Do NOT re-select loaded skills.
3. You may select multiple skills simultaneously if they jointly help solve the task.
4. To inspect auxiliary files or reference scripts of a loaded skill, pass file_path (e.g. 'scripts/run.py', 'references/api.md').
5. Do NOT confuse generic tools (_tool suffix, directly callable) with specialized skills (_skill suffix, must be selected via this tool first).
6. When the user message starts with [use <skill_name>] or mentions a skill by name, you MUST immediately select that skill."""


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

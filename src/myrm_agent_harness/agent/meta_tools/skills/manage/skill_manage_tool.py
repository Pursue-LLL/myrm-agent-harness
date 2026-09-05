"""Skill management meta tool (save / patch / delete / write_file / remove_file / lock / unlock).

[INPUT]
- backends.skills.scanning::ScanningSkillWriteBackend (POS: Framework-level security wrapper for SkillWriteBackend)
- backends.skills.protocols::SkillBackend (POS: Skill backend protocol definition)
- backends.skills.similarity::SkillSimilarityChecker (POS: Skill similarity checking protocol)
- agent.meta_tools.skills.manage._manage_handlers (POS: Internal action handlers and validation logic)
- langchain.tools::tool
- pydantic::BaseModel, Field

[OUTPUT]
- create_skill_manage_tool: factory function for the skill management tool
- resolve_skill_manage_tool_description: resolve localized tool description

[POS]
Skill management meta tool. Enables the Agent to create, update, and delete
skills and their supporting files through a unified interface.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.meta_tools.skills.manage._manage_handlers import (
    SKILL_NAME_PATTERN,
    _extract_user_id,
    _handle_delete,
    _handle_evolution_lock,
    _handle_patch,
    _handle_remove_file,
    _handle_save,
    _handle_write_file,
    _validate_frontmatter,
    _validate_name,
)
from myrm_agent_harness.agent.meta_tools.skills.manage.lock_manager import (
    SkillLockManager,
)
from myrm_agent_harness.utils.locale import is_chinese

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.backends.skills.protocols import SkillBackend
    from myrm_agent_harness.backends.skills.scanning import (
        ScanningSkillWriteBackend,
    )
    from myrm_agent_harness.backends.skills.similarity import SkillSimilarityChecker

logger = logging.getLogger(__name__)

TOOL_DESCRIPTION_EN = """Manage skills (reusable procedural knowledge): save, patch, delete, write_file, remove_file, lock, unlock.

Actions:
- save: Create or fully replace a skill.
- patch: Partially update by replacing a content fragment.
- delete: Remove a skill.
- write_file: Add/overwrite a supporting file (scripts/, references/, templates/, assets/).
- remove_file: Remove a supporting file.
- lock: Lock a skill against automatic overwrites (protects user-customized content).
- unlock: Unlock a skill to re-enable automatic evolution.

IMPORTANT — Self-learning: After completing a complex multi-step task (5+ tool calls), evaluate whether the workflow is reusable and worth saving as a skill BEFORE finalizing your response. Also save when: tricky error fixed with non-obvious solution, non-trivial workflow discovered. Skip simple one-offs.
When to patch: skill outdated, incomplete, or wrong during use — fix immediately.
Confirm with user before creating or deleting.
Good skills: numbered steps, exact commands, pitfalls section, verification steps.

Save content MUST be valid SKILL.md with YAML frontmatter:
---
name: my_skill
description: "Brief description"
---
# Skill Title
<instructions>
"""

TOOL_DESCRIPTION_ZH = """管理技能（可复用流程知识）：save、patch、delete、write_file、remove_file、lock、unlock。

操作：
- save: 创建新技能或全量覆写已有技能。
- patch: 通过替换局部内容片段进行局部更新。
- delete: 删除技能。
- write_file: 新增或覆写辅助文件（scripts/、references/、templates/、assets/）。
- remove_file: 删除辅助文件。
- lock: 锁定技能防止自动优化覆写（保护用户定制内容）。
- unlock: 解锁技能以重新启用自动演化更新。

重要 — 自主学习：在完成复杂多步任务（5+ 次工具调用）后，在最终回复前评估工作流是否可复用且值得保存为技能。在修复非显而易见的棘手错误或发现通用工作流时也应保存。简单单次任务跳过。
patch 时机：技能在执行中使用发现过时、不完整或错误时 — 立即修复。
创建或删除前须向用户确认。
优质技能：编号步骤、确切命令、踩坑要点、验证步骤。

Save 内容必须为带有 YAML frontmatter 的有效 SKILL.md：
---
name: my_skill
description: "简要描述"
---
# 技能标题
<instructions>
"""

TOOL_DESCRIPTION = TOOL_DESCRIPTION_EN

__all__ = [
    "SKILL_NAME_PATTERN",
    "TOOL_DESCRIPTION",
    "TOOL_DESCRIPTION_EN",
    "TOOL_DESCRIPTION_ZH",
    "_extract_user_id",
    "_handle_evolution_lock",
    "_validate_frontmatter",
    "_validate_name",
    "create_skill_manage_tool",
    "resolve_skill_manage_tool_description",
]


def resolve_skill_manage_tool_description(locale: str | None = None) -> str:
    """Resolve LLM-facing skill_manage_tool description."""
    if is_chinese(locale):
        return TOOL_DESCRIPTION_ZH
    return TOOL_DESCRIPTION_EN


def create_skill_manage_tool(
    write_backend: ScanningSkillWriteBackend,
    skill_backend: SkillBackend | None,
    similarity_checker: SkillSimilarityChecker | None = None,
    *,
    locale: str | None = None,
) -> BaseTool:
    """Create the skill management tool.

    Args:
        write_backend: Scanning write backend (enforces security scanning)
        skill_backend: Read-only skill backend (for patch: read current content)
        similarity_checker: Optional checker to warn about semantically similar skills on save.
                           When provided, save actions will query for similar skills and include
                           a warning in the response if high-similarity matches are found.
        locale: Tool description locale (default: English).
    """

    class SkillManageInput(BaseModel):
        action: Literal["save", "patch", "delete", "write_file", "remove_file", "lock", "unlock"] = Field(
            description="Action to perform."
        )
        name: str = Field(description="Skill name (letters, numbers, underscores, hyphens; max 64 chars).")
        content: str = Field(
            default="",
            description="For save: SKILL.md with frontmatter. For write_file: file content.",
        )
        description: str = Field(default="", description="Brief skill description (save only).")
        old_content: str = Field(default="", description="For patch: exact content fragment to replace.")
        new_content: str = Field(default="", description="For patch: replacement fragment.")
        file_path: str = Field(
            default="",
            description="For write_file/remove_file: path under scripts/, references/, templates/, or assets/.",
        )

    @tool("skill_manage_tool", description=resolve_skill_manage_tool_description(locale), args_schema=SkillManageInput)
    async def skill_manage_func(
        action: str,
        name: str,
        content: str = "",
        description: str = "",
        old_content: str = "",
        new_content: str = "",
        file_path: str = "",
        *,
        config: RunnableConfig,
    ) -> str:
        """Manage skills: save, patch, delete, write_file, or remove_file."""
        name_error = _validate_name(name)
        if name_error:
            return name_error

        user_id = _extract_user_id(config)

        lock = SkillLockManager.get_lock(name, user_id)
        async with lock:
            if action == "save":
                return await _handle_save(
                    write_backend,
                    name,
                    content,
                    description,
                    user_id,
                    similarity_checker,
                )
            elif action == "patch":
                return await _handle_patch(
                    write_backend,
                    skill_backend,
                    name,
                    old_content,
                    new_content,
                    user_id,
                )
            elif action == "delete":
                return await _handle_delete(write_backend, name, user_id)
            elif action == "write_file":
                return await _handle_write_file(write_backend, name, file_path, content, user_id)
            elif action == "remove_file":
                return await _handle_remove_file(write_backend, name, file_path, user_id)
            elif action in ("lock", "unlock"):
                return await _handle_evolution_lock(name, locked=(action == "lock"))
            else:
                return (
                    f"Error: Unknown action '{action}'. "
                    f"Use 'save', 'patch', 'delete', 'write_file', 'remove_file', 'lock', or 'unlock'."
                )

    return skill_manage_func

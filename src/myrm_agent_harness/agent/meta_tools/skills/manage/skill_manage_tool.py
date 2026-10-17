"""Skill management meta tool — atomic batches of save/patch/delete/file ops.

[INPUT]
- backends.skills.scanning::ScanningSkillWriteBackend
- manage.batch_runner::run_skill_manage_batch, SkillManageBatchCommittedHook, SkillSnapshotReader

[OUTPUT]
- create_skill_manage_tool: factory for the skill management tool

[POS]
Skill management meta tool. Agent applies one or more operations atomically via operations[].
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.meta_tools.skills.manage._manage_handlers import (
    SKILL_NAME_PATTERN,
    _extract_user_id,
    _validate_name,
)
from myrm_agent_harness.agent.meta_tools.skills.manage.batch_runner import (
    SkillManageBatchCommittedHook,
    SkillSnapshotReader,
    run_skill_manage_batch,
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

TOOL_DESCRIPTION_EN = """Manage skills via atomic batches (operations[]).

Each operation uses action: save | patch | delete | write_file | remove_file | lock | unlock, plus name and action-specific fields (content, old_content/new_content, file_path, description).

Use one operation for a single change; use multiple operations in one call when updating SKILL.md and supporting files together (all succeed or none apply).

For small SKILL.md edits use patch (old_content must match exactly once); use save for new skills or full replacement. lock/unlock wraps a multi-step edit on the same skill.

Confirm with user before create or delete. After complex multi-step tasks (5+ tool calls), consider saving a reusable workflow as a skill.
If a skill you are following is wrong or outdated mid-task, patch it (or ask the user) before you finish.

After a successful batch that changed skill files, the user can undo it from chat Task Steps to restore pre-batch skill content; lock/unlock changes are not part of that undo, and deleting a skill cannot be undone.

save requires valid SKILL.md with YAML frontmatter (name, description)."""

TOOL_DESCRIPTION_ZH = """通过原子批次 operations[] 管理技能。

每条 operation 的 action：save | patch | delete | write_file | remove_file | lock | unlock，并带 name 及对应字段（content、old_content/new_content、file_path、description）。

单改用一个 operation；同时改 SKILL.md 与辅助文件时用同一批 operations（全部成功或全部不生效）。

小范围改 SKILL.md 用 patch（old_content 须唯一精确匹配）；新建或整篇替换用 save。同一技能多步修改前 lock，完成后 unlock。

创建或删除前须向用户确认。复杂多步任务（5+ 次工具调用）后可将可复用流程保存为技能。
执行中若所用技能错误或过时，完成前须 patch 修正（或先询问用户）。

批次全部成功且修改了技能文件后，用户可在对话「任务步骤」中撤销该批次，恢复修改前的技能内容；lock/unlock 的变更不在撤销范围内，删除技能无法撤销。

save 须为带 YAML frontmatter（name、description）的有效 SKILL.md。"""

TOOL_DESCRIPTION = TOOL_DESCRIPTION_EN

__all__ = [
    "SKILL_NAME_PATTERN",
    "TOOL_DESCRIPTION",
    "TOOL_DESCRIPTION_EN",
    "TOOL_DESCRIPTION_ZH",
    "_extract_user_id",
    "_validate_name",
    "create_skill_manage_tool",
    "resolve_skill_manage_tool_description",
]


def resolve_skill_manage_tool_description(locale: str | None = None) -> str:
    """Resolve LLM-facing skill_manage_tool description."""
    if is_chinese(locale):
        return TOOL_DESCRIPTION_ZH
    return TOOL_DESCRIPTION_EN


class SkillOperation(BaseModel):
    action: str = Field(description="save, patch, delete, write_file, remove_file, lock, or unlock.")
    name: str = Field(description="Skill name (letters, numbers, underscores, hyphens; max 64 chars).")
    content: str = Field(default="", description="save or write_file body.")
    description: str = Field(default="", description="save only: short description.")
    old_content: str = Field(default="", description="patch: exact fragment to replace.")
    new_content: str = Field(default="", description="patch: replacement fragment.")
    file_path: str = Field(
        default="",
        description="write_file/remove_file: path under scripts/, references/, templates/, or assets/.",
    )


class SkillManageInput(BaseModel):
    operations: list[SkillOperation] = Field(
        min_length=1,
        max_length=25,
        description="Non-empty list of operations applied atomically.",
    )


def create_skill_manage_tool(
    write_backend: ScanningSkillWriteBackend,
    skill_backend: SkillBackend | None,
    similarity_checker: SkillSimilarityChecker | None = None,
    *,
    locale: str | None = None,
    batch_committed_hook: SkillManageBatchCommittedHook | None = None,
    snapshot_reader: SkillSnapshotReader | None = None,
) -> BaseTool:
    """Create the skill management tool.

    ``snapshot_reader`` is where pre-batch snapshots are read and the first place a patch looks for its skill (see
    ``SkillSnapshotReader``); without one both use ``skill_backend``, which only sees the skills mounted for the turn.
    """

    @tool("skill_manage_tool", description=resolve_skill_manage_tool_description(locale), args_schema=SkillManageInput)
    async def skill_manage_func(
        operations: list[SkillOperation],
        *,
        config: RunnableConfig,
    ) -> str:
        """Apply skill_manage operations atomically."""
        user_id = _extract_user_id(config)
        op_dicts: list[dict[str, object]] = [op.model_dump() for op in operations]
        skill_names = sorted({str(op["name"]) for op in op_dicts})
        locks = [SkillLockManager.get_lock(name, user_id) for name in skill_names]

        async def _execute() -> str:
            return await run_skill_manage_batch(
                write_backend=write_backend,
                skill_backend=skill_backend,
                similarity_checker=similarity_checker,
                operations=op_dicts,
                batch_committed_hook=batch_committed_hook,
                snapshot_reader=snapshot_reader,
                locale=locale,
            )

        async with AsyncExitStack() as stack:
            for lock in locks:
                await stack.enter_async_context(lock)
            return await _execute()

    return skill_manage_func

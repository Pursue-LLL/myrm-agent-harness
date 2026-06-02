"""Consolidation executor — applies consolidation actions to the skill system.

Handles the actual mutation of skills: creating umbrella skills, merging
content, demoting to support files, and inheriting usage statistics.

[INPUT]
- backends.skills.creation_protocols::SkillWriteBackend (POS: Skill write-backend protocol.)
- backends.skills.stats_collector::SkillStatsCollector (POS: Skill usage statistics collector.)
- backends.skills.types::SkillMetadata, SkillUsageStats, SkillLifecycleStatus (POS: Skill types.)
- .types::ConsolidationAction, ConsolidationResult, ConsolidationReport (POS: consolidation types.)

[OUTPUT]
- ConsolidationExecutor: Executes approved consolidation actions.

[POS]
Execution layer for skill consolidation. Performs MERGE/CREATE_UMBRELLA/DEMOTE operations.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus

from .types import (
    ConsolidationAction,
    ConsolidationActionType,
    ConsolidationReport,
    ConsolidationResult,
)

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.creation_protocols import SkillWriteBackend
    from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


class ConsolidationExecutor:
    """Executes approved consolidation actions against the skill system.

    Responsibilities:
    - CREATE_UMBRELLA: Generate and save a new umbrella skill via SkillWriteBackend.
    - MERGE: Expand target skill content, archive sources.
    - DEMOTE: Move source skill content to support files of target.
    - Inherit aggregated usage stats into the umbrella skill.
    - Archive source skills with `merged_into` tracking.
    """

    def __init__(
        self,
        write_backend: SkillWriteBackend,
        stats_collector: SkillStatsCollector,
        all_skills: list[SkillMetadata],
    ) -> None:
        self._write_backend = write_backend
        self._stats = stats_collector
        self._skill_map: dict[str, SkillMetadata] = {s.name: s for s in all_skills}

    async def execute(self, actions: list[ConsolidationAction]) -> ConsolidationReport:
        """Execute a list of approved consolidation actions.

        Args:
            actions: Pre-approved actions from the ConsolidationPlan.

        Returns:
            ConsolidationReport with execution results.
        """
        report = ConsolidationReport(
            skills_before=len([s for s in self._skill_map.values() if s.usage_stats.is_active]),
            started_at=datetime.now(UTC),
        )
        start_time = time.perf_counter()

        for action in actions:
            result = await self._execute_action(action)
            report.results.append(result)
            if result.success:
                report.total_archived += len(result.archived_skills)
                if action.action_type == ConsolidationActionType.CREATE_UMBRELLA:
                    report.total_created += 1

        report.skills_after = report.skills_before - report.total_archived + report.total_created
        report.duration_seconds = time.perf_counter() - start_time

        logger.info(
            "Consolidation complete: %d actions (%d success, %d failed), "
            "skills %d → %d, %.1fs",
            len(actions),
            report.success_count,
            report.failure_count,
            report.skills_before,
            report.skills_after,
            report.duration_seconds,
        )
        return report

    async def _execute_action(self, action: ConsolidationAction) -> ConsolidationResult:
        """Dispatch execution based on action type."""
        try:
            match action.action_type:
                case ConsolidationActionType.CREATE_UMBRELLA:
                    return await self._execute_create_umbrella(action)
                case ConsolidationActionType.MERGE:
                    return await self._execute_merge(action)
                case ConsolidationActionType.DEMOTE:
                    return await self._execute_demote(action)
                case ConsolidationActionType.KEEP:
                    return ConsolidationResult(action=action, success=True)
        except Exception as e:
            logger.error(
                "Consolidation action failed (%s -> %s): %s",
                action.action_type.value,
                action.target_skill,
                e,
            )
            return ConsolidationResult(action=action, success=False, error=str(e))

    async def _execute_create_umbrella(self, action: ConsolidationAction) -> ConsolidationResult:
        """Create a new umbrella skill and archive source skills."""
        source_skills = [self._skill_map[n] for n in action.source_skills if n in self._skill_map]
        if not source_skills:
            return ConsolidationResult(action=action, success=False, error="No source skills found")

        umbrella_content = self._build_umbrella_content(action, source_skills)

        save_result = await self._write_backend.save_skill(
            name=action.target_skill,
            content=umbrella_content,
            description=action.umbrella_description,
        )
        if not save_result.success:
            return ConsolidationResult(
                action=action,
                success=False,
                error=f"Failed to save umbrella: {save_result.error}",
            )

        archived = await self._archive_sources(action.source_skills, action.target_skill)

        self._inherit_stats(source_skills, Path(save_result.saved_path))

        return ConsolidationResult(
            action=action,
            success=True,
            umbrella_skill_path=save_result.saved_path,
            archived_skills=archived,
        )

    async def _execute_merge(self, action: ConsolidationAction) -> ConsolidationResult:
        """Merge source skills into existing target (expand it)."""
        target_skill = self._skill_map.get(action.target_skill)
        if target_skill is None:
            return ConsolidationResult(
                action=action,
                success=False,
                error=f"Target skill '{action.target_skill}' not found",
            )

        source_skills = [self._skill_map[n] for n in action.source_skills if n in self._skill_map]
        if not source_skills:
            return ConsolidationResult(action=action, success=False, error="No source skills found")

        for source in source_skills:
            if source.storage_path:
                await self._write_backend.write_resource(
                    skill_name=action.target_skill,
                    resource_path=f"references/{source.name}.md",
                    content=f"# Merged from: {source.name}\n\n{source.description}\n",
                )

        archived = await self._archive_sources(action.source_skills, action.target_skill)

        target_path = Path(target_skill.storage_path) if target_skill.storage_path else None
        if target_path:
            self._inherit_stats(source_skills, target_path)

        return ConsolidationResult(
            action=action,
            success=True,
            umbrella_skill_path=target_skill.storage_path or "",
            archived_skills=archived,
        )

    async def _execute_demote(self, action: ConsolidationAction) -> ConsolidationResult:
        """Move source skills to support file directory of target."""
        source_skills = [self._skill_map[n] for n in action.source_skills if n in self._skill_map]
        if not source_skills:
            return ConsolidationResult(action=action, success=False, error="No source skills found")

        for source in source_skills:
            resource_path = f"{action.demote_target_dir}/{source.name}.md"
            content = f"# {source.name}\n\n{source.description}\n"
            await self._write_backend.write_resource(
                skill_name=action.target_skill,
                resource_path=resource_path,
                content=content,
            )

        archived = await self._archive_sources(action.source_skills, action.target_skill)

        return ConsolidationResult(
            action=action,
            success=True,
            umbrella_skill_path="",
            archived_skills=archived,
        )

    async def _archive_sources(
        self,
        source_names: tuple[str, ...],
        merged_into: str,
    ) -> tuple[str, ...]:
        """Archive source skills, marking them as merged_into the target."""
        archived: list[str] = []
        for name in source_names:
            skill = self._skill_map.get(name)
            if skill is None or skill.storage_path is None:
                continue

            skill_path = Path(skill.storage_path)
            self._stats.update_lifecycle_status(skill_path, SkillLifecycleStatus.ARCHIVED)

            stats = self._stats.get_stats(skill_path)
            stats.merged_into = merged_into
            self._stats.flush()

            archived.append(name)
            logger.info(
                "Archived skill '%s' (merged into '%s')", name, merged_into
            )

        return tuple(archived)

    def _inherit_stats(
        self,
        source_skills: list[SkillMetadata],
        target_path: Path,
    ) -> None:
        """Aggregate usage stats from sources into the target skill."""
        target_stats = self._stats.get_stats(target_path)
        for source in source_skills:
            target_stats.call_count += source.usage_stats.call_count
            target_stats.success_count += source.usage_stats.success_count
            target_stats.failure_count += source.usage_stats.failure_count
            target_stats.total_duration_ms += source.usage_stats.total_duration_ms

            if source.usage_stats.last_used_at:
                if target_stats.last_used_at is None:
                    target_stats.last_used_at = source.usage_stats.last_used_at
                else:
                    target_stats.last_used_at = max(
                        target_stats.last_used_at,
                        source.usage_stats.last_used_at,
                    )

        self._stats.flush()

    @staticmethod
    def _build_umbrella_content(
        action: ConsolidationAction,
        source_skills: list[SkillMetadata],
    ) -> str:
        """Generate SKILL.md content for a new umbrella skill."""
        keywords_set: set[str] = set()
        for skill in source_skills:
            name_parts = skill.name.lower().removesuffix("_skill").replace("-", " ").replace("_", " ").split()
            keywords_set.update(name_parts)

        keywords_yaml = "\n".join(f"  - {kw}" for kw in sorted(keywords_set)[:15])

        source_list = "\n".join(f"- {s.name}: {s.description}" for s in source_skills)

        content = f"""---
name: {action.target_skill}
description: "{action.umbrella_description}"
keywords:
{keywords_yaml}
---

# {action.target_skill}

{action.umbrella_description}

## Coverage

{action.umbrella_content_outline or "This skill consolidates the following capabilities:"}

## Consolidated From

{source_list}
"""
        return content

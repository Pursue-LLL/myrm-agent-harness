"""Skill Curator Engine — automated lifecycle governance.

Performs a single stateless sweep over all skills:
1. Evaluates each skill against CuratorConfig thresholds
2. Applies lifecycle transitions (active→stale, stale→archived)
3. Optionally runs consolidation pass (umbrella merge)
4. Returns a structured CuratorRunResult

Design principles:
- Stateless: each run is independent, no internal scheduling state
- Non-destructive: worst case is archive (always recoverable)
- Composable: caller decides when/how to trigger (cron, startup, manual)

[INPUT]
- backends.skills.types::SkillMetadata, SkillLifecycleStatus (POS: 技能元数据类型定义)
- backends.skills.forgetting_strategy::DefaultForgettingStrategy, CuratorConfig (POS: Skill forgetting / curator strategies)
- backends.skills.stats_collector::SkillStatsCollector (POS: Skill usage statistics and lifecycle state collector)
- .consolidation::SkillConsolidator (POS: Skill consolidation orchestrator)

[OUTPUT]
- SkillCurator: Stateless curator engine that performs lifecycle sweeps.

[POS]
Skill Curator engine. Orchestrates automated lifecycle governance (stale/archive transitions) and skill consolidation for agent-created skills.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.backends.skills.forgetting_strategy import CuratorConfig, DefaultForgettingStrategy
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus, SkillMetadata

from .types import CuratorRunResult, CuratorTransition

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.backends.skills.creation_protocols import SkillWriteBackend
    from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService

    from .consolidation import ConsolidationPlan, ConsolidationReport

logger = logging.getLogger(__name__)


class SkillCurator:
    """Stateless skill lifecycle curator.

    Evaluates all provided skills against the configured thresholds and
    applies transitions. Each call to run() is a complete, independent sweep.

    Optionally runs a consolidation pass to merge fragmented skills into
    class-level umbrella skills (requires embedding_service and llm).

    Usage:
        curator = SkillCurator(config, stats_collector)
        result = curator.run(skills)

        # With consolidation:
        curator = SkillCurator(config, stats_collector,
            embedding_service=embed, llm=cheap_llm, write_backend=backend)
        result = await curator.run_async(skills)
    """

    def __init__(
        self,
        stats_collector: SkillStatsCollector,
        config: CuratorConfig | None = None,
        *,
        embedding_service: EmbeddingService | None = None,
        llm: BaseChatModel | None = None,
        write_backend: SkillWriteBackend | None = None,
    ) -> None:
        self._config = config or CuratorConfig()
        self._strategy = DefaultForgettingStrategy(self._config)
        self._stats = stats_collector
        self._embedding_service = embedding_service
        self._llm = llm
        self._write_backend = write_backend

    @property
    def config(self) -> CuratorConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def consolidation_available(self) -> bool:
        """Whether consolidation can run (all dependencies present)."""
        return (
            self._config.consolidation_enabled
            and self._embedding_service is not None
            and self._llm is not None
            and self._write_backend is not None
        )

    def run(self, skills: list[SkillMetadata], *, force: bool = False) -> CuratorRunResult:
        """Execute a single curator sweep over the provided skills.

        Evaluates each skill and applies state transitions where warranted.
        Transitions are persisted immediately via SkillStatsCollector.

        Note: This synchronous version does NOT run consolidation.
        Use run_async() for full curator sweep including consolidation.

        Args:
            skills: All skills to evaluate (caller handles which skills to include)
            force: If True, bypass the enabled check (for manual triggers)

        Returns:
            CuratorRunResult with details of all transitions performed
        """
        if not force and not self._config.enabled:
            return CuratorRunResult()

        result = CuratorRunResult(skills_scanned=len(skills))
        now = datetime.now(UTC)

        for skill in skills:
            try:
                self._evaluate_skill(skill, now, result)
            except Exception as e:
                result.errors.append(f"{skill.name}: {e}")
                logger.warning("Curator error evaluating skill '%s': %s", skill.name, e)

        self._apply_lru_eviction(skills, now, result)

        if result.total_transitions > 0:
            logger.info(
                "Curator sweep complete: %d skills scanned, %d transitions "
                "(%d stale, %d archived), %d pinned skipped",
                result.skills_scanned,
                result.total_transitions,
                result.stale_count,
                result.archived_count,
                result.skipped_pinned,
            )
        else:
            logger.debug("Curator sweep complete: %d skills scanned, no transitions needed", result.skills_scanned)

        return result

    async def run_async(
        self,
        skills: list[SkillMetadata],
        *,
        force: bool = False,
        consolidation_dry_run: bool = True,
    ) -> tuple[CuratorRunResult, ConsolidationPlan | ConsolidationReport | None]:
        """Execute a full curator sweep including optional consolidation.

        Args:
            skills: All skills to evaluate.
            force: If True, bypass the enabled check.
            consolidation_dry_run: If True, return consolidation plan without executing.

        Returns:
            Tuple of (lifecycle_result, consolidation_result).
            consolidation_result is None if consolidation is disabled/unavailable.
        """
        lifecycle_result = self.run(skills, force=force)

        consolidation_result: ConsolidationPlan | ConsolidationReport | None = None
        if self.consolidation_available:
            consolidation_result = await self._run_consolidation(
                skills, dry_run=consolidation_dry_run
            )

        return lifecycle_result, consolidation_result

    async def _run_consolidation(
        self,
        skills: list[SkillMetadata],
        *,
        dry_run: bool = True,
    ) -> ConsolidationPlan | ConsolidationReport | None:
        """Run consolidation pass if dependencies are available."""
        if not self.consolidation_available:
            return None

        assert self._embedding_service is not None
        assert self._llm is not None
        assert self._write_backend is not None

        from .consolidation import SkillConsolidator

        consolidator = SkillConsolidator(
            embedding_service=self._embedding_service,
            llm=self._llm,
            write_backend=self._write_backend,
            stats_collector=self._stats,
            min_skills_for_consolidation=self._config.consolidation_min_skills,
            min_cluster_size=self._config.consolidation_min_cluster_size,
            similarity_threshold=self._config.consolidation_similarity_threshold,
        )

        try:
            return await consolidator.run(skills, dry_run=dry_run)
        except Exception as e:
            logger.error("Consolidation pass failed: %s", e)
            return None

    def _apply_lru_eviction(
        self, skills: list[SkillMetadata], now: datetime, result: CuratorRunResult
    ) -> None:
        """Evict least-recently-used skills when active count exceeds max_skills."""
        already_transitioned = {t.skill_name for t in result.transitions}
        lru_candidates = self._strategy.select_lru_candidates(skills)
        for reason in lru_candidates:
            if reason.skill_name in already_transitioned:
                continue

            skill = next((s for s in skills if s.name == reason.skill_name), None)
            if skill is None:
                continue

            skill_path = Path(skill.storage_path) if skill.storage_path else None
            if skill_path is None:
                result.errors.append(f"{skill.name}: no storage_path for LRU eviction")
                continue

            current_status = str(SkillLifecycleStatus(skill.usage_stats.lifecycle_status).value)
            target_status = str(SkillLifecycleStatus(reason.target_status).value)

            self._stats.update_lifecycle_status(skill_path, reason.target_status)
            result.transitions.append(
                CuratorTransition(
                    skill_name=skill.name,
                    skill_path=str(skill_path),
                    from_status=current_status,
                    to_status=target_status,
                    reason_type=reason.reason_type,
                    reason_message=reason.reason_message,
                    timestamp=now,
                )
            )
            logger.info("Curator LRU eviction: %s → %s for '%s'", current_status, target_status, skill.name)

    def _evaluate_skill(self, skill: SkillMetadata, now: datetime, result: CuratorRunResult) -> None:
        """Evaluate a single skill and apply transition if needed."""
        if skill.usage_stats.pinned:
            result.skipped_pinned += 1
            return

        reason = self._strategy.should_forget(skill)
        if reason is None:
            return

        current_status = str(SkillLifecycleStatus(skill.usage_stats.lifecycle_status).value)
        target_status = str(SkillLifecycleStatus(reason.target_status).value)

        if current_status == target_status:
            return

        skill_path = Path(skill.storage_path) if skill.storage_path else None
        if skill_path is None:
            result.errors.append(f"{skill.name}: no storage_path, cannot persist transition")
            return

        self._stats.update_lifecycle_status(skill_path, reason.target_status)

        transition = CuratorTransition(
            skill_name=skill.name,
            skill_path=str(skill_path),
            from_status=current_status,
            to_status=target_status,
            reason_type=reason.reason_type,
            reason_message=reason.reason_message,
            timestamp=now,
        )
        result.transitions.append(transition)

        logger.info(
            "Curator: %s → %s (reason: %s) for skill '%s'",
            current_status,
            target_status,
            reason.reason_type,
            skill.name,
        )

"""Skill consolidation orchestrator — coordinates the full pipeline.

Wires together ClusterDetector → ConsolidationJudge → ConsolidationExecutor
into a single cohesive consolidation run, with dry-run support.

[INPUT]
- .cluster_detector::ClusterDetector (POS: Cluster detection layer.)
- .judge::ConsolidationJudge (POS: LLM judge layer.)
- .executor::ConsolidationExecutor (POS: Execution layer.)
- .types::ConsolidationPlan, ConsolidationReport (POS: consolidation types.)
- backends.skills.types::SkillMetadata, SkillLifecycleStatus (POS: Skill types.)
- backends.skills.stats_collector::SkillStatsCollector (POS: Stats collector.)
- backends.skills.creation_protocols::SkillWriteBackend (POS: Write backend.)
- toolkits.retriever.embedding.base::EmbeddingService (POS: Embedding service.)
- langchain_core.language_models::BaseChatModel (POS: LLM base class.)

[OUTPUT]
- SkillConsolidator: Top-level orchestrator for the consolidation pipeline.

[POS]
Top-level orchestrator. Single entry point for skill consolidation (dry-run and execute).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus

from .cluster_detector import ClusterDetector
from .executor import ConsolidationExecutor
from .judge import ConsolidationJudge
from .types import ConsolidationPlan, ConsolidationReport

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.backends.skills.creation_protocols import SkillWriteBackend
    from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService

logger = logging.getLogger(__name__)

_DEFAULT_MIN_SKILLS_FOR_CONSOLIDATION = 10
_DEFAULT_MIN_CLUSTER_SIZE = 3
_DEFAULT_SIMILARITY_THRESHOLD = 0.75


class SkillConsolidator:
    """Top-level orchestrator for the skill consolidation pipeline.

    Pipeline stages:
    1. Filter: Select eligible skills (active, non-pinned, non-protected).
    2. Detect: Identify clusters via prefix + embedding similarity.
    3. Judge: LLM evaluates each cluster and produces a ConsolidationPlan.
    4. Execute: Apply approved actions (or return plan for dry-run preview).

    Supports two modes:
    - dry_run=True: Returns ConsolidationPlan without executing (for GUI preview).
    - dry_run=False: Executes the plan and returns ConsolidationReport.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        llm: BaseChatModel,
        write_backend: SkillWriteBackend,
        stats_collector: SkillStatsCollector,
        *,
        min_skills_for_consolidation: int = _DEFAULT_MIN_SKILLS_FOR_CONSOLIDATION,
        min_cluster_size: int = _DEFAULT_MIN_CLUSTER_SIZE,
        similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        self._detector = ClusterDetector(
            embedding_service,
            min_cluster_size=min_cluster_size,
            similarity_threshold=similarity_threshold,
        )
        self._judge = ConsolidationJudge(llm)
        self._write_backend = write_backend
        self._stats_collector = stats_collector
        self._min_skills = min_skills_for_consolidation

    async def run(
        self,
        skills: list[SkillMetadata],
        *,
        dry_run: bool = True,
    ) -> ConsolidationPlan | ConsolidationReport:
        """Run the consolidation pipeline.

        Args:
            skills: All skills from the skill backend.
            dry_run: If True, return plan without execution. If False, execute.

        Returns:
            ConsolidationPlan (dry_run=True) or ConsolidationReport (dry_run=False).
        """
        eligible = self._filter_eligible(skills)

        if len(eligible) < self._min_skills:
            logger.info(
                "Consolidation skipped: only %d eligible skills (minimum: %d)",
                len(eligible),
                self._min_skills,
            )
            return ConsolidationPlan() if dry_run else ConsolidationReport()

        clusters = await self._detector.detect(eligible)
        if not clusters:
            logger.info("Consolidation: no clusters detected")
            return ConsolidationPlan() if dry_run else ConsolidationReport()

        plan = await self._judge.judge_clusters(clusters, skills)

        if plan.is_empty:
            logger.info("Consolidation: judge determined no actions needed")
            return plan if dry_run else ConsolidationReport()

        logger.info(
            "Consolidation plan: %d actions, %d skills affected, estimated reduction: %d",
            len(plan.actions),
            plan.total_skills_affected,
            plan.estimated_reduction,
        )

        if dry_run:
            return plan

        executor = ConsolidationExecutor(
            self._write_backend,
            self._stats_collector,
            skills,
        )
        report = await executor.execute(plan.actions)
        return report

    @staticmethod
    def _filter_eligible(skills: list[SkillMetadata]) -> list[SkillMetadata]:
        """Filter skills eligible for consolidation analysis.

        Excludes:
        - Pinned skills
        - Evolution-locked skills (user-created, protected from automation)
        - Archived skills
        - Skills without storage_path (MCP skills)
        """
        return [
            s
            for s in skills
            if not s.usage_stats.pinned
            and not s.evolution_locked
            and s.usage_stats.lifecycle_status != SkillLifecycleStatus.ARCHIVED
            and s.storage_path is not None
        ]

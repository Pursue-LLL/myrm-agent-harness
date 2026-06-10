"""Skill evolution engine - Core of self-evolution system.

Implements 4 evolution types + evidence-driven evolution as a lightweight orchestrator:
- FIX: Auto-repair failed skills via trace analysis
- DERIVED: Optimize based on feedback
- CAPTURED: Learn from patterns
- OPTIMIZE_DESCRIPTION: Refine description for better matching
- Evidence-driven: Aggregated success+failure analysis with action routing

Returns standardized EvolutionProposal objects, delegating application
and persistence to the business layer (Server/GUI).

[INPUT]
- agent.skills.evolution.db.store::SkillStore (POS: SQLite persistence for skill evolution system.)
- agent.skills.evolution.execution.evaluator::BatchEvaluator (POS: Batch Evaluator for Skill Evolution.)
- agent.skills.evolution.pipeline.trace_analyzer::TraceAnalyzer (POS: Trace Analyzer for Skill Evolution.)
- agent.skills.evolution.pipeline.variant_generator::VariantGenerator (POS: Variant Generator for Skill Evolution.)
- agent.skills.evolution.core.types::SkillEvidenceGroup (POS: Data types for skill evolution system.)
- agent.event_log.protocol::EventLogBackend (POS: Protocol contract. Framework provides FileEventLogBackend; business layer may extend with SQLite / PostgreSQL implementations.)
- agent.skills.evolution.pipeline.structured_extractor::StructuredExtractor (POS: Provides SkillCaptureResult, StructuredExtractor.)
- agent.skills.evolution.safety.validator::SkillValidator (POS: Skill evolution validation system.)
- agent.skills.evolution.execution.sandbox_validator::SandboxValidator (POS: Sandbox validation for evolved skills.)

[OUTPUT]
- SkillEvolutionEngine: Core orchestrator for skill self-evolution.

[POS]
Skill evolution engine - Core of self-evolution system.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.agent.skills.evolution.core.proposal_builder import (
    ProposalBuilder,
)
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EnvironmentFingerprint,
    EvolutionProposal,
    EvolutionRequest,
    EvolutionType,
    SkillEvidenceGroup,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore
from myrm_agent_harness.agent.skills.evolution.execution.evaluator import BatchEvaluator
from myrm_agent_harness.agent.skills.evolution.pipeline.trace_analyzer import (
    TraceAnalyzer,
)
from myrm_agent_harness.agent.skills.evolution.pipeline.variant_generator import (
    VariantGenerator,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.event_log.protocols import EventLogBackend

logger = logging.getLogger(__name__)

__all__ = ["SkillEvolutionEngine"]


class SkillEvolutionEngine:
    """Core orchestrator for skill self-evolution.

    Framework layer component:
    - Analyzes full execution traces (TraceAnalyzer)
    - Generates multiple variants (VariantGenerator)
    - Evaluates variants via LLM-as-judge (BatchEvaluator)
    - Outputs standardized EvolutionProposal
    """

    def __init__(
        self,
        store: SkillStore,
        llm: BaseChatModel | None = None,
        event_log_backend: EventLogBackend | None = None,
        max_concurrent_evolutions: int = 5,
        num_variants_per_evolution: int = 3,
    ):
        """Initialize the lightweight evolution engine.

        Args:
            store: SkillStore for persistence (read-only in engine).
            llm: LLM client for generating evolved skills.
            event_log_backend: Optional backend for trace extraction.
            max_concurrent_evolutions: Max concurrent evolution tasks.
            num_variants_per_evolution: Number of variants to generate per run.
        """
        self._store = store
        self._llm = llm
        self._semaphore = asyncio.Semaphore(max_concurrent_evolutions)
        self._num_variants = num_variants_per_evolution

        # Initialize sub-modules
        self._trace_analyzer = TraceAnalyzer(event_log_backend) if event_log_backend else None
        self._variant_generator = VariantGenerator(llm)
        self._evaluator = BatchEvaluator(llm)
        self._proposal_builder = ProposalBuilder()

    async def fix_skill(
        self,
        skill_id: str,
        error_message: str,
        task_context: str | None = None,
        session_id: str | None = None,
        env_fingerprint: EnvironmentFingerprint | None = None,
    ) -> EvolutionProposal | None:
        """FIX evolution: Propose repair for a failed skill.

        Implements Retrieve-Before-Generate (Scan & Select):
        First searches the store for an existing high-confidence fix matching
        the error signature and environment. If found, reuses it.
        Otherwise, falls back to LLM generation.
        """
        old_skill = self._store.get_skill(skill_id)
        if not old_skill:
            logger.error(f"FIX evolution: skill not found: {skill_id}")
            return None

        if old_skill.evolution_locked:
            logger.warning(f"FIX skipped: skill '{old_skill.name}' is locked.")
            return None

        logger.info(f"FIX evolution started for '{old_skill.name}'")

        # 0. Scan & Select (Retrieve-Before-Generate)
        # Try to find an existing skill that might fix this
        # We search using the error message as a heuristic signature
        if error_message:
            # Extract a short signature from the error message
            # For tracebacks, the last non-empty line contains the actual error (e.g., "ModuleNotFoundError: ...")
            lines = [line.strip() for line in error_message.strip().split("\n") if line.strip()]
            error_sig = lines[-1][:200] if lines else error_message[:200]

            candidate_skills = await self._store.search_skills(
                query=error_sig,
                env_fingerprint=env_fingerprint,
                limit=1,
                min_effective_rate=0.8,  # Only reuse highly proven fixes
            )
            if candidate_skills:
                match = candidate_skills[0]
                # Don't match against itself
                if match.skill_id != old_skill.skill_id:
                    logger.info(f"Scan & Select: Found existing high-confidence fix '{match.name}' for error.")
                    return self._proposal_builder.build_proposal(
                        skill=old_skill,
                        evolution_type=EvolutionType.FIX,
                        best_variant=match.content,
                        score=match.metrics.effective_rate,
                        reasoning=f"Retrieved existing high-confidence fix ({match.name}) matching error signature.",
                        task_context=task_context or "",
                        trajectory="Retrieved from SkillStore (No LLM generation needed).",
                        is_general=True,
                    )

        # 1. Extract Trajectory
        trajectory = ""
        if self._trace_analyzer and session_id:
            trajectory = await self._trace_analyzer.extract_trajectory_with_code(session_id, old_skill)
        else:
            trajectory = f"Trajectory extraction not available. Error: {error_message}"

        # 1.5 Fetch historical constraints to prevent repeated mistakes
        constraints = self._store.get_evolution_constraints(skill_id, limit=5)
        formatted_constraints = "\n".join([f"- {c}" for c in constraints]) if constraints else ""

        # 2. Generate Variants
        feedback = f"Error: {error_message}\nContext: {task_context or 'None'}"
        variants = await self._variant_generator.generate_variants(
            skill=old_skill,
            feedback=feedback,
            trajectory=trajectory,
            num_variants=self._num_variants,
            constraints=formatted_constraints,
        )

        if not variants:
            return None

        # 3. Evaluate Variants
        best_variant, score, reason, is_general = await self._evaluator.evaluate_variants(
            original_skill=old_skill,
            variants=variants,
            feedback=feedback,
            trajectory=trajectory,
        )

        # 4. Build Proposal
        proposal = self._proposal_builder.build_proposal(
            skill=old_skill,
            evolution_type=EvolutionType.FIX,
            best_variant=best_variant,
            score=score,
            reasoning=reason,
            task_context=task_context or "",
            trajectory=trajectory,
            is_general=is_general,
        )

        # 4.5 Persist learning: record successful fix as evolution constraint
        if proposal and score >= 0.7:
            constraint = f"FIX succeeded (score={score:.2f}): {error_message[:100]} → {reason[:100]}"
            try:
                await self._store.add_evolution_constraint(skill_id, constraint)
            except Exception as e:
                logger.debug("Failed to persist FIX constraint for %s: %s", skill_id, e)

        return proposal

    async def derive_skill_simple(self, skill_id: str, user_feedback: str) -> EvolutionProposal | None:
        """DERIVED evolution: Optimize skill based on feedback."""
        old_skill = self._store.get_skill(skill_id)
        if not old_skill:
            logger.error(f"DERIVED evolution: skill not found: {skill_id}")
            return None

        if old_skill.evolution_locked:
            logger.warning(f"DERIVED skipped: '{old_skill.name}' is locked.")
            return None

        logger.info(f"DERIVED evolution started for '{old_skill.name}'")

        trajectory = "User initiated optimization."
        constraints = self._store.get_evolution_constraints(skill_id, limit=5)
        formatted_constraints = "\n".join([f"- {c}" for c in constraints]) if constraints else ""

        variants = await self._variant_generator.generate_variants(
            skill=old_skill,
            feedback=user_feedback,
            trajectory=trajectory,
            num_variants=self._num_variants,
            constraints=formatted_constraints,
        )

        if not variants:
            return None

        best_variant, score, reason, is_general = await self._evaluator.evaluate_variants(
            original_skill=old_skill,
            variants=variants,
            feedback=user_feedback,
            trajectory=trajectory,
        )

        return self._proposal_builder.build_proposal(
            skill=old_skill,
            evolution_type=EvolutionType.DERIVED,
            best_variant=best_variant,
            score=score,
            reasoning=reason,
            task_context=user_feedback,
            trajectory=trajectory,
            is_general=is_general,
        )

    async def evolve_from_evidence(
        self,
        evidence: SkillEvidenceGroup,
        min_evidence: int = 3,
        min_failures: int = 1,
    ) -> EvolutionProposal | None:
        """Evidence-driven evolution: Propose repair using aggregated success+failure data.

        Unlike fix_skill() which reacts to a single failure, this method
        analyzes the full evidence picture to make smarter decisions:
        - Sees which scenarios work (invariants to protect)
        - Sees which scenarios fail (targets to fix)
        - Skips evolution when evidence is insufficient

        Args:
            evidence: Aggregated evidence group for one skill.
            min_evidence: Minimum total executions required (default 3).
            min_failures: Minimum failures required to justify evolution (default 1).

        Returns:
            EvolutionProposal or None if evidence insufficient or skill not found.
        """
        if not evidence.has_sufficient_evidence(min_total=min_evidence, min_failures=min_failures):
            logger.debug(
                "Skipping evidence evolution for '%s': insufficient evidence (%d total, %d failures, need %d/%d)",
                evidence.skill_name,
                evidence.total_evidence,
                len(evidence.failure_cases),
                min_evidence,
                min_failures,
            )
            return None

        # Skip LLM evaluation when evidence confidence is too low (scattered/transient errors)
        if evidence.confidence < 0.4:
            logger.info(
                "Skipping evidence evolution for '%s': low confidence (%.2f < 0.4) — "
                "errors are likely transient/environmental, not skill defects",
                evidence.skill_name,
                evidence.confidence,
            )
            return None

        old_skill = self._store.get_skill(evidence.skill_id)
        if not old_skill:
            logger.error(f"Evidence evolution: skill not found: {evidence.skill_id}")
            return None

        if old_skill.evolution_locked:
            logger.warning(f"Evidence evolution skipped: skill '{old_skill.name}' is locked.")
            return None

        logger.info(
            "Evidence evolution started for '%s' (success=%d, failure=%d, rate=%.1f%%)",
            old_skill.name,
            len(evidence.success_cases),
            len(evidence.failure_cases),
            evidence.evidence_success_rate * 100,
        )

        # Action routing: decide whether to fix content or optimize description
        selected_action = self._select_evolution_action(old_skill, evidence)
        if selected_action == EvolutionType.OPTIMIZE_DESCRIPTION:
            logger.info(
                "Action router selected OPTIMIZE_DESCRIPTION for '%s' (fallback_rate=%.1f%%, effective_rate=%.1f%%)",
                old_skill.name,
                old_skill.metrics.fallback_rate * 100,
                old_skill.metrics.effective_rate * 100,
            )
            return await self.optimize_description(old_skill.skill_id, evidence)

        constraints = self._store.get_evolution_constraints(evidence.skill_id, limit=5)
        formatted_constraints = "\n".join([f"- {c}" for c in constraints]) if constraints else ""

        variants = await self._variant_generator.generate_variants_from_evidence(
            skill=old_skill,
            evidence=evidence,
            num_variants=self._num_variants,
            constraints=formatted_constraints,
        )

        if not variants:
            return None

        feedback_summary = (
            f"Evidence-driven: {len(evidence.success_cases)} successes, "
            f"{len(evidence.failure_cases)} failures. "
            f"Common errors: {'; '.join(evidence.common_error_patterns[:3]) or 'N/A'}"
        )

        best_variant, score, reason, is_general = await self._evaluator.evaluate_variants(
            original_skill=old_skill,
            variants=variants,
            feedback=feedback_summary,
            trajectory="Evidence-based analysis (aggregated across multiple executions).",
        )

        return self._proposal_builder.build_proposal(
            skill=old_skill,
            evolution_type=EvolutionType.FIX,
            best_variant=best_variant,
            score=score,
            reasoning=f"[Evidence-driven] {reason}",
            task_context=feedback_summary,
            trajectory=f"Evidence: {evidence.total_evidence} executions, "
            f"success_rate={evidence.evidence_success_rate:.1%}",
            is_general=is_general,
        )

    async def optimize_description(
        self,
        skill_id: str,
        evidence: SkillEvidenceGroup | None = None,
    ) -> EvolutionProposal | None:
        """OPTIMIZE_DESCRIPTION evolution: Rewrite only the skill description.

        Used when the skill body is correct but gets matched to wrong tasks.
        Only changes the description (Use-when / NOT-for conditions), zero risk
        to the skill content itself.
        """
        old_skill = self._store.get_skill(skill_id)
        if not old_skill:
            logger.error("OPTIMIZE_DESCRIPTION: skill not found: %s", skill_id)
            return None

        if old_skill.evolution_locked:
            logger.warning("OPTIMIZE_DESCRIPTION skipped: '%s' is locked.", old_skill.name)
            return None

        logger.info("OPTIMIZE_DESCRIPTION started for '%s'", old_skill.name)

        desc_variants = await self._variant_generator.generate_description_variants(
            skill=old_skill,
            evidence=evidence,
            num_variants=self._num_variants,
        )

        if not desc_variants:
            return None

        best_desc, score, reason, _ = await self._evaluator.evaluate_description_variants(
            original_skill=old_skill,
            variants=desc_variants,
        )

        return self._proposal_builder.build_proposal(
            skill=old_skill,
            evolution_type=EvolutionType.OPTIMIZE_DESCRIPTION,
            best_variant=best_desc,
            score=score,
            reasoning=f"[Description optimization] {reason}",
            task_context="Description-only update for better skill matching.",
            trajectory="",
            is_general=True,
        )

    @staticmethod
    def _select_evolution_action(skill: SkillRecord, evidence: SkillEvidenceGroup) -> EvolutionType:
        """Rule-based action routing: decide FIX vs OPTIMIZE_DESCRIPTION.

        Heuristic (zero LLM cost):
        - High fallback_rate + high effective_rate → description is too broad
        - Low effective_rate → content has real bugs
        """
        metrics = evidence.metrics_snapshot or skill.metrics
        if metrics.fallback_rate > 0.3 and metrics.effective_rate > 0.7 and metrics.total_selections >= 5:
            return EvolutionType.OPTIMIZE_DESCRIPTION
        return EvolutionType.FIX

    async def extract_skill_from_slice(
        self,
        session_id: str,
        tool_call_ids: list[str],
        agent_id: str | None = None,
    ) -> EvolutionProposal | None:
        """SLICE_EXTRACTION: Extract a skill from a slice of execution trace.

        Args:
            session_id: The session ID to fetch trace from.
            tool_call_ids: List of tool call IDs that form the coherent slice.
            agent_id: Optional agent ID for scoping.

        Returns:
            EvolutionProposal or None if skipped/rejected.
        """
        if not self._trace_analyzer:
            logger.warning("extract_skill_from_slice skipped: No TraceAnalyzer (event_log_backend missing)")
            return None

        logger.info(f"Extracting skill from slice: session={session_id}, calls={len(tool_call_ids)}")

        # 1. Fetch trace slice via TraceAnalyzer
        slice_result = await self._trace_analyzer.analyze_slice(
            session_id=session_id,
            tool_call_ids=tool_call_ids,
        )
        if not slice_result or not slice_result.is_coherent:
            logger.info(
                f"Slice {session_id} ({len(tool_call_ids)} calls) rejected by AST/Static analyzer: Not a coherent workflow."
            )
            return None

        # 2. Extract pattern using LLM
        trajectory = slice_result.formatted_trace
        from myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor import (
            StructuredExtractor,
        )

        if not self._llm:
            return None

        extractor = StructuredExtractor(self._llm)
        result = await extractor.extract_from_trajectory(trajectory)

        if not result or not result.is_general or result.confidence < 0.8:
            return None

        from myrm_agent_harness.agent.skills.evolution.safety.validator import (
            SkillValidator,
        )

        validator = SkillValidator()
        temp_record = SkillRecord(
            skill_id=result.name,
            name=result.name,
            description="Validation draft",
            content=result.content,
            path="",
            lineage=None,  # type: ignore
        )

        validation = validator.validate(temp_record)
        if not validation.valid:
            return None

        from myrm_agent_harness.agent.skills.evolution.execution.sandbox_validator import (
            SandboxValidator,
        )

        sandbox = SandboxValidator()
        is_safe, _ = await sandbox.dry_run_skill(temp_record)
        if not is_safe:
            return None

        from datetime import datetime

        proposal = EvolutionProposal(
            skill_id=result.name,
            evolution_type=EvolutionType.SLICE_EXTRACTION,
            original_content="",
            proposed_content=result.content,
            diff="",
            score=result.confidence,
            reasoning=f"Auto-extracted from slice. Safety: {result.safety_analysis}",
            task_context=f"Session slice {len(tool_call_ids)} calls",
            is_general=result.is_general,
            created_at=datetime.now(),
            agent_id=agent_id,
        )

        return proposal

    async def capture_skill_from_trajectory(
        self,
        trajectory: str,
        session_id: str,
        env_fingerprint: EnvironmentFingerprint | None = None,
    ) -> EvolutionProposal | None:
        """CAPTURED evolution: Learn from conversation trajectory.

        Returns a proposal for a brand new skill if a reusable pattern is detected.
        """
        logger.info(f"CAPTURED evolution started for session {session_id}.")

        from myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor import (
            StructuredExtractor,
        )

        if not self._llm:
            logger.error("No LLM provided to SkillEvolutionEngine.")
            return None

        extractor = StructuredExtractor(self._llm)
        result = await extractor.extract_from_trajectory(trajectory)

        if not result:
            logger.debug(f"No valid skill extracted from trajectory of session {session_id}")
            return None

        if not result.is_general:
            logger.debug(f"Skill {result.name} rejected: not generalizable.")
            return None

        if result.confidence < 0.8:
            logger.debug(f"Skill {result.name} rejected: low confidence ({result.confidence}).")
            return None

        # Deduplication check (Trigram / Similarity)
        active_skills = self._store.get_active_skills()
        if active_skills:
            from difflib import SequenceMatcher

            max_sim = 0.0
            similar_skill = None
            for s in active_skills:
                # Compare content similarity
                sim = SequenceMatcher(None, s.content, result.content).ratio()
                if sim > max_sim:
                    max_sim = sim
                    similar_skill = s.name

            if max_sim > 0.85:
                logger.warning(
                    f"Skill {result.name} rejected: Highly similar to existing skill {similar_skill} (sim={max_sim:.2f})."
                )
                return None

        # Minimal mock skill for proposal builder
        SkillRecord(
            skill_id=result.name,
            name=result.name,
            description=result.safety_analysis,  # Store analysis here temporarily
            content="",
            path="",
            lineage=None,  # type: ignore
        )

        from myrm_agent_harness.agent.skills.evolution.safety.validator import (
            SkillValidator,
        )

        validator = SkillValidator()
        # Create a temporary record with the new content to validate
        temp_record = SkillRecord(
            skill_id=result.name,
            name=result.name,
            description="Validation draft",
            content=result.content,
            path="",
            lineage=None,  # type: ignore
        )

        validation = validator.validate(temp_record)
        if not validation.valid:
            logger.warning(f"Skill {result.name} rejected: Validation failed - {validation.errors}")
            return None

        from myrm_agent_harness.agent.skills.evolution.execution.sandbox_validator import (
            SandboxValidator,
        )

        sandbox = SandboxValidator()
        is_safe, error_msg = await sandbox.dry_run_skill(temp_record)
        if not is_safe:
            logger.warning(f"Skill {result.name} rejected: Sandbox dry-run failed: {error_msg}")
            return None

        # Build proposal
        from datetime import datetime

        proposal = EvolutionProposal(
            skill_id=result.name,
            evolution_type=EvolutionType.CAPTURED,
            original_content="",
            proposed_content=result.content,
            diff="",
            score=result.confidence,
            reasoning=f"Auto-extracted. Safety: {result.safety_analysis}",
            task_context=f"Session {session_id}",
            is_general=result.is_general,
            environment=env_fingerprint,
            created_at=datetime.now(),
        )

        return proposal

    async def evolve_multiple_concurrent(self, requests: list[EvolutionRequest]) -> list[EvolutionProposal | None]:
        """Evolve multiple skills concurrently with rate limiting."""
        if not requests:
            return []

        async def _evolve_with_limit(req: EvolutionRequest) -> EvolutionProposal | None:
            async with self._semaphore:
                if req.evolution_type == EvolutionType.FIX:
                    return await self.fix_skill(req.skill_id or "", req.reason)
                elif req.evolution_type == EvolutionType.DERIVED:
                    return await self.derive_skill_simple(req.skill_id or "", req.user_feedback)
                elif req.evolution_type == EvolutionType.OPTIMIZE_DESCRIPTION:
                    return await self.optimize_description(req.skill_id or "")
                elif req.evolution_type == EvolutionType.CAPTURED:
                    return None
                return None

        results = await asyncio.gather(*[_evolve_with_limit(req) for req in requests], return_exceptions=True)

        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Concurrent evolution request {i} failed: {result}")
                final_results.append(None)
            else:
                final_results.append(result)

        return final_results

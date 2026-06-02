"""Periodic skill health monitoring and proactive evolution trigger.

Implements P0-4 Metric Monitor: Scans active skills periodically,
diagnoses health issues with 6-indicator system, and triggers evolution
with optional LLM confirmation.

[INPUT]
- agent.skills.evolution.core.engine::SkillEvolutionEngine (POS: Skill evolution engine - Core of self-evolution system.)
- agent.skills.evolution.core.types::EvolutionProposal, (POS: Data types for skill evolution system.)
- agent.skills.evolution.db.store::SkillStore (POS: SQLite persistence for skill evolution system.)

[OUTPUT]
- MetricMonitor: Periodic skill health monitor with proactive evolution tr...

[POS]
Periodic skill health monitoring and proactive evolution trigger.
"""

import asyncio
import contextlib
import logging
from typing import Any

from myrm_agent_harness.agent.skills.evolution.core.engine import SkillEvolutionEngine
from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionProposal, EvolutionType, SkillRecord
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore

logger = logging.getLogger(__name__)

# Diagnostic thresholds (configurable)
_FALLBACK_THRESHOLD = 0.5  # High fallback rate triggers FIX
_HIGH_APPLIED_FOR_FIX = 0.3  # High applied rate (for FIX diagnosis)
_LOW_COMPLETION_THRESHOLD = 0.5  # Low completion rate triggers FIX
_MODERATE_EFFECTIVE_THRESHOLD = 0.6  # Moderate effectiveness triggers DERIVED
_MIN_APPLIED_FOR_DERIVED = 0.2  # Minimum applied rate for DERIVED


class MetricMonitor:
    """Periodic skill health monitor with proactive evolution triggering.

    Scans active skills, diagnoses health with 6-indicator system,
    and triggers FIX/DERIVED evolution with optional LLM confirmation.

    Key features:
    - 6-indicator diagnosis: fallback_rate, applied_rate, completion_rate, effective_rate
    - Optional LLM confirmation to prevent false positives
    - Configurable scan interval and diagnostic thresholds
    - Background execution to avoid blocking main thread

    Example:
        monitor = MetricMonitor(
            store=skill_store,
            engine=evolution_engine,
            llm_client=llm_client,
            scan_interval=10,  # Every 10 skill executions
            enable_llm_confirmation=True,  # Recommend enabled
        )
        await monitor.scan_and_evolve()
    """

    def __init__(
        self,
        store: SkillStore,
        engine: SkillEvolutionEngine,
        llm_client: Any | None = None,
        *,
        scan_interval: int = 10,
        enable_llm_confirmation: bool = True,
        fallback_threshold: float = _FALLBACK_THRESHOLD,
        high_applied_for_fix: float = _HIGH_APPLIED_FOR_FIX,
        low_completion_threshold: float = _LOW_COMPLETION_THRESHOLD,
        moderate_effective_threshold: float = _MODERATE_EFFECTIVE_THRESHOLD,
        min_applied_for_derived: float = _MIN_APPLIED_FOR_DERIVED,
        min_selections: int = 5,
        max_concurrent_evolutions: int = 5,
        on_evolution_complete: Any | None = None,
        on_scan_complete: Any | None = None,
        enable_tool_degradation: bool = False,
        tool_quality_monitor: Any | None = None,
        dependency_tracker: Any | None = None,
        tool_degradation_threshold: float = 0.7,
    ):
        """Initialize metric monitor.

        Args:
            store: Skill store
            engine: Evolution engine
            llm_client: LLM client for confirmation (required if enable_llm_confirmation=True)
            scan_interval: Scan every N executions (default 10)
            enable_llm_confirmation: Enable LLM confirmation (default True, recommended)
            fallback_threshold: Fallback rate threshold (default 0.5)
            high_applied_for_fix: Applied rate threshold for FIX (default 0.3)
            low_completion_threshold: Completion rate threshold (default 0.5)
            moderate_effective_threshold: Effective rate threshold for DERIVED (default 0.6)
            min_applied_for_derived: Minimum applied rate for DERIVED (default 0.2)
            min_selections: Minimum selections to consider (default 5)
            max_concurrent_evolutions: Max concurrent evolutions (default 5, for rate limiting)
            on_evolution_complete: Optional callback(skill_id, evo_type, success, duration_ms)
            on_scan_complete: Optional callback(stats)
            enable_tool_degradation: Enable tool degradation detection (default False, opt-in)
            tool_quality_monitor: ToolQualityMonitor instance (required if enable_tool_degradation=True)
            dependency_tracker: SkillDependencyTracker instance (required if enable_tool_degradation=True)
            tool_degradation_threshold: Tool degradation threshold for success rate (default 0.7)
        """
        self._store = store
        self._engine = engine
        self._llm_client = llm_client
        self._scan_interval = scan_interval
        self._enable_llm_confirmation = enable_llm_confirmation
        self._fallback_threshold = fallback_threshold
        self._high_applied_for_fix = high_applied_for_fix
        self._low_completion_threshold = low_completion_threshold
        self._moderate_effective_threshold = moderate_effective_threshold
        self._min_applied_for_derived = min_applied_for_derived
        self._min_selections = min_selections
        self._execution_count = 0

        # Tool degradation tracking (P1-6)
        self._enable_tool_degradation = enable_tool_degradation
        self._tool_quality_monitor = tool_quality_monitor
        self._dependency_tracker = dependency_tracker
        self._tool_degradation_threshold = tool_degradation_threshold
        self._addressed_degradations: dict[str, set[str]] = {}  # tool_key → {skill_id}

        # Background scheduler state
        self._background_task: asyncio.Task[None] | None = None
        self._running = False

        # Monitoring stats
        self._total_scans = 0
        self._total_evolutions = 0
        self._llm_confirmations = 0
        self._llm_rejections = 0

        # Event callbacks (optional)
        self._on_evolution_complete = on_evolution_complete
        self._on_scan_complete = on_scan_complete

        # Concurrency control
        self._max_concurrent_evolutions = max_concurrent_evolutions
        self._semaphore = asyncio.Semaphore(max_concurrent_evolutions)

        if enable_llm_confirmation and not llm_client:
            raise ValueError("LLM client required when enable_llm_confirmation=True")

        if enable_tool_degradation and (not tool_quality_monitor or not dependency_tracker):
            raise ValueError("tool_quality_monitor and dependency_tracker required when enable_tool_degradation=True")

    def increment_execution_count(self) -> None:
        """Increment execution count (called by business layer after each skill execution)."""
        self._execution_count += 1

    def should_scan(self) -> bool:
        """Check if should scan based on execution count.

        Returns:
            True if should scan
        """
        return self._execution_count % self._scan_interval == 0

    async def start(self) -> None:
        """Start background scheduler for automatic periodic scanning.

        Enables "out-of-the-box" monitoring - business layer only needs to call
        increment_execution_count() after each skill execution.

        Example:
            monitor = MetricMonitor(...)
            await monitor.start()  # Start automatic background scanning
            # ... later ...
            await monitor.stop()   # Graceful shutdown
        """
        if self._running:
            logger.warning("[MetricMonitor] Already running")
            return

        self._running = True
        self._background_task = asyncio.create_task(self._background_scheduler())
        logger.info("[MetricMonitor] Background scheduler started")

    async def stop(self) -> None:
        """Stop background scheduler gracefully."""
        if not self._running:
            return

        self._running = False
        if self._background_task:
            self._background_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._background_task
        logger.info("[MetricMonitor] Background scheduler stopped")

    async def _background_scheduler(self) -> None:
        """Background scheduler loop - automatically triggers scans.

        Polls execution count every 5 seconds and triggers scan when needed.
        Handles exceptions gracefully to ensure continuous operation.
        """
        while self._running:
            try:
                await asyncio.sleep(5)  # Poll interval

                if self.should_scan():
                    logger.info("[MetricMonitor] Triggering automatic scan")
                    try:
                        await self.scan_and_evolve()
                    except Exception as e:
                        logger.error(f"[MetricMonitor] Scan failed: {e}", exc_info=True)
                        # Continue running despite errors

            except asyncio.CancelledError:
                logger.debug("[MetricMonitor] Background scheduler cancelled")
                break
            except Exception as e:
                logger.error(f"[MetricMonitor] Background scheduler error: {e}", exc_info=True)
                await asyncio.sleep(10)  # Backoff on error

    def get_stats(self) -> dict[str, Any]:
        """Get monitoring statistics.

        Returns:
            Dict with monitoring stats:
            - total_scans: Total scans performed
            - total_evolutions: Total evolutions triggered
            - llm_confirmations: LLM confirmations (yes)
            - llm_rejections: LLM rejections (no)
            - llm_confirmation_rate: Confirmation rate (0.0-1.0)
            - is_running: Whether background scheduler is running
        """
        llm_total = self._llm_confirmations + self._llm_rejections
        return {
            "total_scans": self._total_scans,
            "total_evolutions": self._total_evolutions,
            "llm_confirmations": self._llm_confirmations,
            "llm_rejections": self._llm_rejections,
            "llm_confirmation_rate": (self._llm_confirmations / llm_total if llm_total > 0 else 0.0),
            "is_running": self._running,
        }

    async def scan_and_evolve(self) -> list[EvolutionProposal]:
        """Scan active skills and trigger evolution for unhealthy ones.

        Two-phase process:
        1. Rule-based diagnosis (relaxed thresholds)
        2. Optional LLM confirmation (if enabled)

        Returns:
            List of generated evolution proposals
        """
        self._total_scans += 1  # Track scan count

        # Phase 1: Diagnose candidates
        candidates: list[tuple[SkillRecord, EvolutionType, str]] = []
        all_active = self._store.get_active_skills()

        for record in all_active:
            # Skip skills with insufficient data
            if record.metrics.total_selections < self._min_selections:
                continue

            # Diagnose health
            evo_type, direction = self._diagnose_skill_health(record)
            if evo_type is None:
                continue

            # Phase 2: LLM confirmation (if enabled)
            if self._enable_llm_confirmation:
                confirmed = await self._llm_confirm_evolution(
                    record=record, proposed_type=evo_type, proposed_direction=direction
                )
                if not confirmed:
                    logger.debug(f"[MetricMonitor] LLM rejected evolution for skill '{record.name}' ({evo_type.value})")
                    continue

            candidates.append((record, evo_type, direction))

        if not candidates:
            logger.info("[MetricMonitor] No skills need evolution")
            return []

        # Phase 3: Execute evolutions concurrently (with rate limiting)
        logger.info(f"[MetricMonitor] Triggering evolution for {len(candidates)} skills")
        tasks = [
            self._evolve_skill_with_callback(record, evo_type, direction) for record, evo_type, direction in candidates
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        evolved: list[EvolutionProposal] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                record, evo_type, _ = candidates[i]
                logger.error(f"[MetricMonitor] Evolution failed for skill '{record.name}' ({evo_type.value}): {result}")
            elif result is not None:
                evolved.append(result)
                self._total_evolutions += 1  # Track successful evolution

        logger.info(f"[MetricMonitor] Successfully generated {len(evolved)} proposals")

        # Phase 4: Check tool degradation (P1-6, opt-in)
        tool_degradation_evolved: list[EvolutionProposal] = []
        if self._enable_tool_degradation:
            try:
                tool_degradation_evolved = await self.check_tool_degradation()
                if tool_degradation_evolved:
                    logger.info(
                        f"[MetricMonitor] Tool degradation triggered {len(tool_degradation_evolved)} evolutions"
                    )
                    evolved.extend(tool_degradation_evolved)
                    self._total_evolutions += len(tool_degradation_evolved)
            except Exception as e:
                logger.error(f"[MetricMonitor] Tool degradation check failed: {e}", exc_info=True)

        # Trigger scan complete callback
        if self._on_scan_complete:
            try:
                stats = self.get_stats()
                if asyncio.iscoroutinefunction(self._on_scan_complete):
                    await self._on_scan_complete(stats)
                else:
                    self._on_scan_complete(stats)
            except Exception as e:
                logger.error(f"[MetricMonitor] Scan complete callback failed: {e}")

        return evolved

    def _diagnose_skill_health(self, record: SkillRecord) -> tuple[EvolutionType | None, str]:
        """Diagnose skill health based on 6-indicator system.

        3 diagnostic rules:
        1. High fallback_rate → FIX (selected but not applied)
        2. High applied_rate + Low completion_rate → FIX (applied but failed)
        3. Moderate effective_rate → DERIVED (works sometimes)

        Args:
            record: Skill record to diagnose

        Returns:
            (EvolutionType, direction_message) or (None, "") if healthy
        """
        metrics = record.metrics

        # Rule 1: High fallback rate → skill frequently selected but not used
        if metrics.fallback_rate > self._fallback_threshold:
            return EvolutionType.FIX, (
                f"High fallback rate ({metrics.fallback_rate:.0%}): "
                f"skill is frequently selected but not applied, "
                f"suggesting instructions are unclear or outdated."
            )

        # Rule 2: Applied often but rarely completes → instructions are wrong
        if (
            metrics.applied_rate > self._high_applied_for_fix
            and metrics.completion_rate < self._low_completion_threshold
        ):
            return EvolutionType.FIX, (
                f"Low completion rate ({metrics.completion_rate:.0%}) despite "
                f"high applied rate ({metrics.applied_rate:.0%}): "
                f"skill instructions may be incorrect or incomplete."
            )

        # Rule 3: Moderate effectiveness → could be better
        if (
            metrics.effective_rate < self._moderate_effective_threshold
            and metrics.applied_rate > self._min_applied_for_derived
        ):
            return EvolutionType.DERIVED, (
                f"Moderate effectiveness ({metrics.effective_rate:.0%}): "
                f"skill works sometimes but could be enhanced with "
                f"better error handling or alternative approaches."
            )

        return None, ""

    async def _llm_confirm_evolution(
        self, record: SkillRecord, proposed_type: EvolutionType, proposed_direction: str
    ) -> bool:
        """Ask LLM to confirm evolution decision with historical context.

        Prevents false positives from rigid threshold-based rules.
        Loads recent execution analyses to provide concrete failure examples.

        Args:
            record: Skill record
            proposed_type: Proposed evolution type
            proposed_direction: Diagnostic message

        Returns:
            True if LLM confirms evolution needed
        """
        if not self._llm_client:
            return True  # Skip confirmation if LLM not available

        # Load recent analyses (concrete failure cases)
        recent_analyses = await self._store.load_analyses(skill_id=record.skill_id, limit=5)

        metrics = record.metrics

        # Format recent analyses for prompt
        analyses_text = ""
        if recent_analyses:
            analyses_text = "\n\n**Recent Execution History**:\n"
            for i, analysis in enumerate(recent_analyses, 1):
                status = " Success" if analysis.success else " Failed"
                analyses_text += f"{i}. {status}\n"
                if analysis.error_message:
                    analyses_text += f" Error: {analysis.error_message[:100]}\n"
                if analysis.root_cause:
                    analyses_text += f" Root cause: {analysis.root_cause[:100]}\n"

        prompt = f"""You are a skill quality expert. Review the following skill and decide if evolution is needed.

**Skill**: {record.name}
**Description**: {record.description}

**Metrics**:
- Total selections: {metrics.total_selections}
- Fallback rate: {metrics.fallback_rate:.0%}
- Applied rate: {metrics.applied_rate:.0%}
- Completion rate: {metrics.completion_rate:.0%}
- Effective rate: {metrics.effective_rate:.0%}

**Proposed evolution**: {proposed_type.value}
**Reason**: {proposed_direction}{analyses_text}

Based on the metrics and recent history, does this skill truly need {proposed_type.value} evolution? Answer ONLY "yes" or "no".
"""

        try:
            response = await self._llm_client.generate(prompt=prompt, max_tokens=10)
            content = response.get("content", "").strip().lower()
            return content.startswith("yes")
        except Exception as e:
            logger.warning(f"[MetricMonitor] LLM confirmation failed, defaulting to skip: {e}")
            return False  # Conservative: skip on error

    async def _evolve_skill_with_callback(
        self, record: SkillRecord, evo_type: EvolutionType, direction: str
    ) -> EvolutionProposal | None:
        """Execute evolution with semaphore and callback.

        Wraps _evolve_skill() with:
        - Semaphore for rate limiting
        - Duration tracking
        - Evolution complete callback

        Args:
            record: Skill record
            evo_type: Evolution type
            direction: Diagnostic message

        Returns:
            EvolutionProposal or None if failed
        """
        import time

        async with self._semaphore:  # Rate limiting
            start_time = time.time()
            result = await self._evolve_skill(record, evo_type, direction)
            duration_ms = int((time.time() - start_time) * 1000)

            # Trigger evolution complete callback
            if self._on_evolution_complete:
                try:
                    if asyncio.iscoroutinefunction(self._on_evolution_complete):
                        await self._on_evolution_complete(
                            skill_id=record.skill_id,
                            evo_type=evo_type.value,
                            success=(result is not None),
                            duration_ms=duration_ms,
                        )
                    else:
                        self._on_evolution_complete(
                            skill_id=record.skill_id,
                            evo_type=evo_type.value,
                            success=(result is not None),
                            duration_ms=duration_ms,
                        )
                except Exception as e:
                    logger.error(f"[MetricMonitor] Evolution complete callback failed: {e}")

            return result

    async def _evolve_skill(
        self, record: SkillRecord, evo_type: EvolutionType, direction: str
    ) -> EvolutionProposal | None:
        """Execute evolution for a single skill.

        Args:
            record: Skill record
            evo_type: Evolution type
            direction: Diagnostic message

        Returns:
            Evolution proposal or None if failed
        """
        try:
            # Extract task_context from recent failures
            task_context = ""
            if evo_type == EvolutionType.FIX:
                recent_analyses = await self._store.load_analyses(skill_id=record.skill_id, limit=1)
                if recent_analyses and recent_analyses[0].task_context:
                    task_context = recent_analyses[0].task_context

            if evo_type == EvolutionType.FIX:
                return await self._engine.fix_skill(
                    skill_id=record.skill_id, error_message=direction, task_context=task_context
                )
            elif evo_type == EvolutionType.DERIVED:
                return await self._engine.derive_skill_simple(skill_id=record.skill_id, user_feedback=direction)
            else:
                logger.error(f"[MetricMonitor] Unsupported evolution type: {evo_type}")
                return None
        except Exception as e:
            logger.error(f"[MetricMonitor] Evolution failed for '{record.name}': {e}")
            return None

    async def check_tool_degradation(self) -> list[SkillRecord]:
        """Check for tool degradation and trigger skill evolution (P1-6).

        Workflow:
        1. Get degraded tools from ToolQualityMonitor
        2. Find affected skills via DependencyTracker
        3. Optional LLM confirmation
        4. Trigger FIX evolution
        5. Track addressed degradations to prevent loops

        Returns:
            List of evolved skill records
        """
        if not self._enable_tool_degradation:
            return []

        # Get degraded tools
        degraded_tools = self._tool_quality_monitor.get_degraded_tools(
            success_threshold=self._tool_degradation_threshold
        )

        if not degraded_tools:
            return []

        logger.info(f"[ToolDegradation] Detected {len(degraded_tools)} degraded tools")

        # Clear recovered tools from tracking
        current_tool_keys = {t.tool_key for t in degraded_tools}
        recovered = [k for k in self._addressed_degradations if k not in current_tool_keys]
        for k in recovered:
            logger.debug(f"[ToolDegradation] Tool '{k}' recovered, clearing addressed set")
            del self._addressed_degradations[k]

        # Process each degraded tool
        evolution_tasks = []
        for tool_record in degraded_tools:
            tool_key = tool_record.tool_key
            addressed = self._addressed_degradations.get(tool_key, set())

            # Find affected skills
            affected_skills = self._dependency_tracker.find_skills_by_tool(tool_key)
            if not affected_skills:
                logger.debug(f"[ToolDegradation] No skills depend on '{tool_key}'")
                continue

            logger.info(f"[ToolDegradation] Tool '{tool_key}' affects {len(affected_skills)} skills")

            # Process each affected skill
            for skill_id in affected_skills:
                # Anti-loop: skip if already addressed
                if skill_id in addressed:
                    logger.debug(f"[ToolDegradation] Skipping '{skill_id}' (already addressed for '{tool_key}')")
                    continue

                # Load skill record
                record = self._store.load_record(skill_id)
                if not record or not record.is_active:
                    continue

                # Build diagnostic message
                direction = (
                    f"Tool `{tool_key}` degraded (success_rate={tool_record.recent_success_rate:.0%}, "
                    f"p95_latency={tool_record.p95_latency:.0f}ms, degradation_type={tool_record.degradation_type}). "
                    f"Update skill to handle tool failures gracefully or suggest alternatives."
                )

                # Optional LLM confirmation
                if self._enable_llm_confirmation:
                    confirmed = await self._llm_confirm_evolution(
                        record=record, evo_type=EvolutionType.FIX, direction=direction
                    )
                    if not confirmed:
                        logger.debug(f"[ToolDegradation] LLM rejected evolution for '{skill_id}' (tool={tool_key})")
                        # Still mark as addressed to avoid repeated LLM calls
                        self._addressed_degradations.setdefault(tool_key, set()).add(skill_id)
                        continue

                # Schedule evolution
                task = self._evolve_skill_with_callback(record=record, evo_type=EvolutionType.FIX, direction=direction)
                evolution_tasks.append(task)

                # Mark as addressed
                self._addressed_degradations.setdefault(tool_key, set()).add(skill_id)

        # Execute all evolutions concurrently
        if evolution_tasks:
            results = await asyncio.gather(*evolution_tasks, return_exceptions=True)
            successful = [r for r in results if isinstance(r, EvolutionProposal)]
            logger.info(f"[ToolDegradation] Completed {len(successful)}/{len(evolution_tasks)} evolutions")
            return successful

        return []

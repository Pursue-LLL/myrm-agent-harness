"""Dual-path degradation gate for post-fetch memory passage screening.

Executes local pattern scanning and optional fast micro-model evaluation with
graceful degradation to local-only screening on latency/outage.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .pattern_scanner import scan_passage_patterns
from .types import (
    MemoryPassageUnit,
    MemoryScreeningPolicy,
    PassageScreeningVerdict,
    PassageVerdictStatus,
    ScreeningPathMode,
)


class DualPathDegradationGate:
    """Orchestrates dual-path evaluation (jev+local vs local-only) for retrieved memory passages."""

    def __init__(
        self,
        policy: MemoryScreeningPolicy | None = None,
        remote_scorer: Callable[[str], float] | None = None,
    ) -> None:
        self.policy = policy or MemoryScreeningPolicy()
        self.remote_scorer = remote_scorer

    def evaluate_single(
        self,
        passage: MemoryPassageUnit,
        force_local_only: bool = False,
    ) -> PassageScreeningVerdict:
        """Evaluate a single passage with local-first scanning followed by remote scoring if applicable."""
        # 1. Local-first pattern scanning
        patterns = scan_passage_patterns(
            text=passage.content,
            enable_url_scan=self.policy.enable_url_exfiltration_scan,
            enable_cmd_scan=self.policy.enable_command_risk_scan,
        )

        if patterns:
            # Immediate local rejection
            reason = f"matched_{len(patterns)}_threat_patterns:{patterns[0].pattern_category}"
            return PassageScreeningVerdict(
                passage_id=passage.passage_id,
                status=PassageVerdictStatus.TOXIC,
                confidence_score=0.95,
                pathway=ScreeningPathMode.LOCAL_ONLY if force_local_only else ScreeningPathMode.JEV_AND_LOCAL,
                matched_patterns=patterns,
                rejection_reason=reason,
            )

        # 2. Remote scoring pass if enabled and available
        if (
            self.policy.remote_scorer_enabled
            and self.remote_scorer is not None
            and not force_local_only
        ):
            try:
                score = float(self.remote_scorer(passage.content))
                if score >= self.policy.threshold:
                    return PassageScreeningVerdict(
                        passage_id=passage.passage_id,
                        status=PassageVerdictStatus.TOXIC,
                        confidence_score=score,
                        pathway=ScreeningPathMode.JEV_AND_LOCAL,
                        matched_patterns=[],
                        rejection_reason=f"remote_threat_score:{score:.2f}>={self.policy.threshold}",
                    )
                return PassageScreeningVerdict(
                    passage_id=passage.passage_id,
                    status=PassageVerdictStatus.CLEAN,
                    confidence_score=score,
                    pathway=ScreeningPathMode.JEV_AND_LOCAL,
                    matched_patterns=[],
                    rejection_reason="",
                )
            except Exception as exc:
                # Fallback to local clean on remote outage
                return PassageScreeningVerdict(
                    passage_id=passage.passage_id,
                    status=PassageVerdictStatus.CLEAN,
                    confidence_score=0.0,
                    pathway=ScreeningPathMode.LOCAL_ONLY,
                    matched_patterns=[],
                    rejection_reason=f"remote_scorer_exception:{type(exc).__name__}",
                )

        # Local-only clean pass
        return PassageScreeningVerdict(
            passage_id=passage.passage_id,
            status=PassageVerdictStatus.CLEAN,
            confidence_score=0.0,
            pathway=ScreeningPathMode.LOCAL_ONLY,
            matched_patterns=[],
            rejection_reason="",
        )

    def evaluate_batch(
        self,
        passages: list[MemoryPassageUnit],
    ) -> tuple[list[PassageScreeningVerdict], ScreeningPathMode, str]:
        """Evaluate a batch of candidate passages, automatically managing degradation."""
        verdicts: list[PassageScreeningVerdict] = []
        pathway_chosen = (
            ScreeningPathMode.JEV_AND_LOCAL
            if (self.policy.remote_scorer_enabled and self.remote_scorer is not None)
            else ScreeningPathMode.LOCAL_ONLY
        )
        degradation_note = ""

        start_time = time.perf_counter()
        force_local_only = pathway_chosen == ScreeningPathMode.LOCAL_ONLY

        for passage in passages:
            elapsed = time.perf_counter() - start_time
            if not force_local_only and elapsed > self.policy.remote_timeout_seconds:
                force_local_only = True
                pathway_chosen = ScreeningPathMode.LOCAL_ONLY
                degradation_note = (
                    f"Timeout ({elapsed:.2f}s > {self.policy.remote_timeout_seconds}s) triggered local-only degradation"
                )

            verdict = self.evaluate_single(passage, force_local_only=force_local_only)
            verdicts.append(verdict)

        return verdicts, pathway_chosen, degradation_note

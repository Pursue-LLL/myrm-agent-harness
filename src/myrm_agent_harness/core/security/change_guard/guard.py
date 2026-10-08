"""ChangeGuard engine orchestrating review lanes, authority gates, and evidence hardening.

[INPUT]
- Hardened findings, exception definitions, and policy configuration.

[OUTPUT]
- ChangeGuardEvaluationResult with distinct Lane A gates and Lane B review questions.

[POS]
- Main engine for WS1-WS5 Agent Authority ChangeGuard.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .exceptions_manager import ChangeGuardExceptionsManager
from .lane_evaluator import ChangeGuardLaneEvaluator
from .types import (
    CanonicalOutcome,
    ChangeClass,
    ChangeGuardEvaluationResult,
    ChangeGuardException,
    ChangeGuardPolicyConfig,
    EvidenceRecord,
    EvidenceType,
    Gateability,
    HardenedFinding,
    ProvenanceClass,
)


class ChangeGuard:
    """Orchestrates change evaluation across distinct review lanes with evidence hardening."""

    def __init__(
        self,
        config: ChangeGuardPolicyConfig | None = None,
        exceptions_manager: ChangeGuardExceptionsManager | None = None,
    ) -> None:
        self._config = config or ChangeGuardPolicyConfig()
        self._exceptions_manager = exceptions_manager or ChangeGuardExceptionsManager()
        self._evaluator = ChangeGuardLaneEvaluator(self._config)

    @property
    def config(self) -> ChangeGuardPolicyConfig:
        """Return the current policy configuration."""
        return self._config

    @property
    def exceptions_manager(self) -> ChangeGuardExceptionsManager:
        """Return the exceptions manager instance."""
        return self._exceptions_manager

    def add_exception(self, exception: ChangeGuardException) -> None:
        """Register a file-backed exception."""
        self._exceptions_manager.add_exception(exception)

    def evaluate_changes(
        self,
        findings: tuple[HardenedFinding, ...],
        current_time_iso: str | None = None,
    ) -> ChangeGuardEvaluationResult:
        """Evaluate findings across review lanes applying exception controls."""
        eff_time = (
            current_time_iso
            if current_time_iso is not None
            else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        unexempted, applied_exc, stale_exc = self._exceptions_manager.evaluate_findings(
            findings=findings,
            current_time_iso=eff_time,
        )

        summary_a, summary_b, highest_change = self._evaluator.evaluate_lanes(unexempted)

        # Consolidated overall outcome determination
        if summary_a.outcome == CanonicalOutcome.BLOCK or (self._config.strict_exceptions and stale_exc):
            overall = CanonicalOutcome.BLOCK
        elif summary_b.outcome == CanonicalOutcome.REVIEW_REQUIRED:
            overall = CanonicalOutcome.REVIEW_REQUIRED
        elif summary_b.outcome == CanonicalOutcome.WARN:
            overall = CanonicalOutcome.WARN
        else:
            overall = CanonicalOutcome.PASS

        return ChangeGuardEvaluationResult(
            overall_outcome=overall,
            lane_a=summary_a,
            lane_b=summary_b,
            highest_change_class=highest_change,
            applied_exceptions=applied_exc,
            stale_or_expired_exceptions=stale_exc,
        )


def build_hardened_finding(
    finding_id: str,
    rule_id: str,
    category: str,
    target_object: str,
    message: str,
    change_class: ChangeClass = ChangeClass.LOW_CHANGE,
    provenance_class: ProvenanceClass = ProvenanceClass.DETECTED,
    gateability: Gateability = Gateability.DETERMINISTIC,
    evidence_type: EvidenceType = EvidenceType.STATIC_CONFIG,
    source_file: str = "config.yaml",
    line_number: int | None = None,
    pattern_matched: str | None = None,
    sha256_digest: str | None = None,
) -> HardenedFinding:
    """Helper factory constructing a strictly validated HardenedFinding."""
    evidence = EvidenceRecord(
        evidence_type=evidence_type,
        source_file=source_file,
        line_number=line_number,
        pattern_matched=pattern_matched,
        sha256_digest=sha256_digest,
        description=f"Evidence for {rule_id} on {target_object}",
    )
    return HardenedFinding(
        finding_id=finding_id,
        rule_id=rule_id,
        category=category,
        target_object=target_object,
        change_class=change_class,
        provenance_class=provenance_class,
        gateability=gateability,
        evidence=evidence,
        message=message,
    )

"""Audit Coverage Engine orchestrating explicit coverage disclosure and repair workflows.

[INPUT]
- ApplicationModel, CoverageScopeItem, AuditFinding, RepairPatch.

[OUTPUT]
- ExplicitAuditCoverageReport containing audited scopes, challenged findings, and replay bundles.

[POS]
- Harness core security engine. Coordinates application model validation, adversarial
  challenge reviews, explicit coverage metrics, and replayable repair generation.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from myrm_agent_harness.core.security.audit_coverage.independent_challenge import (
    IndependentChallengeReviewer,
)
from myrm_agent_harness.core.security.audit_coverage.model_contract import (
    ApplicationModelContract,
)
from myrm_agent_harness.core.security.audit_coverage.repair_bundle import (
    ReplayableRepairEngine,
)
from myrm_agent_harness.core.security.audit_coverage.types import (
    ApplicationModel,
    AuditFinding,
    ChallengeVerdict,
    CoverageCategory,
    CoverageScopeItem,
    CoverageStatus,
    ExplicitAuditCoverageReport,
    RepairPatch,
    ReplayableRepairBundle,
)

logger = logging.getLogger(__name__)


class AuditCoverageEngine:
    """Orchestrator for application security audit with explicit coverage and repair bundles."""

    def __init__(
        self,
        application_model: ApplicationModel,
        challenge_reviewer: IndependentChallengeReviewer | None = None,
        repair_engine: ReplayableRepairEngine | None = None,
    ) -> None:
        self._model = application_model
        self._contract = ApplicationModelContract(application_model)
        self._reviewer = challenge_reviewer or IndependentChallengeReviewer()
        self._repair_engine = repair_engine or ReplayableRepairEngine()

        self._scopes: dict[CoverageCategory, CoverageScopeItem] = {}
        self._findings: list[AuditFinding] = []
        self._bundles: list[ReplayableRepairBundle] = []
        self._audit_id = f"audit_{uuid.uuid4().hex[:12]}"

    @property
    def application_model(self) -> ApplicationModel:
        """Application model being audited."""
        return self._model

    def register_scope(self, scope: CoverageScopeItem) -> None:
        """Register or update explicit coverage disclosure for a specific security category."""
        self._scopes[scope.category] = scope

    def register_scopes(self, scopes: Sequence[CoverageScopeItem]) -> None:
        """Batch register coverage scope disclosures."""
        for s in scopes:
            self._scopes[s.category] = s

    def record_finding(
        self,
        finding: AuditFinding,
        codebase_context: str = "",
        auto_challenge: bool = True,
    ) -> AuditFinding:
        """Record a finding, asserting application model boundaries and executing adversarial challenge."""
        # 1. Assert application model boundary
        self._contract.validate_finding(finding)

        # 2. Adversarial challenge
        processed_finding = (
            self._reviewer.challenge_finding(finding, codebase_context)
            if auto_challenge
            else finding
        )

        self._findings.append(processed_finding)
        return processed_finding

    def attach_repair_bundle(
        self,
        finding_id: str,
        patches: Sequence[RepairPatch],
        replay_script: str,
        verify_immediately: bool = True,
    ) -> ReplayableRepairBundle:
        """Create and attach a replayable repair bundle to a confirmed audit finding."""
        matching_findings = [f for f in self._findings if f.finding_id == finding_id]
        if not matching_findings:
            raise ValueError(f"Finding with ID '{finding_id}' not found in audit session.")

        target_finding = matching_findings[0]
        bundle = self._repair_engine.create_bundle(target_finding, patches, replay_script)

        if verify_immediately:
            bundle = self._repair_engine.verify_bundle(bundle)
            # Upgrade finding tier to TESTED
            updated_finding = self._repair_engine.upgrade_finding_verification(target_finding, bundle)
            idx = self._findings.index(target_finding)
            self._findings[idx] = updated_finding

        self._bundles.append(bundle)
        return bundle

    def generate_coverage_report(self) -> ExplicitAuditCoverageReport:
        """Compile comprehensive audit report with explicit coverage metrics and confirmed findings."""
        # Ensure all standard categories have explicit coverage disclosure
        all_categories = list(CoverageCategory)
        final_scopes: list[CoverageScopeItem] = []

        total_percentage = 0.0
        for cat in all_categories:
            if cat in self._scopes:
                item = self._scopes[cat]
                final_scopes.append(item)
                total_percentage += item.coverage_percentage
            else:
                # Explicitly disclose uncovered category
                uncovered = CoverageScopeItem(
                    category=cat,
                    status=CoverageStatus.UNCOVERED_UNSUPPORTED,
                    audit_surface="Not evaluated in current audit profile",
                    coverage_percentage=0.0,
                    uncovered_reason="Scope was not registered in active audit plan",
                )
                final_scopes.append(uncovered)

        avg_coverage = round(total_percentage / len(all_categories), 2)
        audit_id = self._audit_id

        # Filter out findings that were successfully refuted during independent challenge
        active_findings = tuple(
            f for f in self._findings if f.challenge_status != ChallengeVerdict.CHALLENGED_REFUTED
        )

        return ExplicitAuditCoverageReport(
            audit_id=audit_id,
            application_model=self._model,
            scopes=tuple(final_scopes),
            findings=active_findings,
            repair_bundles=tuple(self._bundles),
            overall_coverage_percentage=avg_coverage,
        )

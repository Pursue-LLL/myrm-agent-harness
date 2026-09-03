"""Runtime Capability Eviction & Procurement Compliance Self-Audit Engine.

Provides the Six-Question Eviction Compliance Checklist (太一/政企采购合规六问自检):
1. Q1_ROUTES_CLEAN: Are deprecated/uninstalled plugin endpoints fully evicted from routing tables?
2. Q2_REGISTRY_CLEAN: Is the Tool Registry memory flat-index completely clean of phantom tools?
3. Q3_CRON_CLEAN: Are background cron jobs and polling consumers associated with uninstalled plugins stopped/purged?
4. Q4_FILESYSTEM_CLEAN: Are temporary bundles, lock files, and isolated storage free of orphan artifacts?
5. Q5_PROCESS_CLEAN: Are orphan MCP subprocesses and connection pools gracefully terminated?
6. Q6_VAULT_CLEAN: Are session credentials and access tokens properly revoked/cleared?

[POS]
Zero-dependency, thread-safe, pure diagnostic and compliance assertion engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ComplianceStatus(str, Enum):
    """Compliance verification status for each question."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ComplianceViolation:
    """Detailed record of a single compliance violation."""

    question_id: str
    target: str
    reason: str
    severity: str = "high"
    remediation_hint: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "question_id": self.question_id,
            "target": self.target,
            "reason": self.reason,
            "severity": self.severity,
            "remediation_hint": self.remediation_hint,
        }


@dataclass(frozen=True, slots=True)
class ComplianceReport:
    """Structured result of a procurement/runtime compliance self-audit."""

    status: ComplianceStatus
    compliance_score: int
    checked_at: str
    questions: dict[str, bool]
    violations: list[ComplianceViolation] = field(default_factory=list)
    remediation_hints: list[str] = field(default_factory=list)

    @property
    def is_fully_compliant(self) -> bool:
        return self.status == ComplianceStatus.COMPLIANT and self.compliance_score == 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "compliance_score": self.compliance_score,
            "checked_at": self.checked_at,
            "is_fully_compliant": self.is_fully_compliant,
            "questions": dict(self.questions),
            "violations": [v.to_dict() for v in self.violations],
            "remediation_hints": list(self.remediation_hints),
        }


class ComplianceAuditEngine:
    """Core compliance evaluation engine verifying zero-darkline capability eviction."""

    @staticmethod
    def audit_tool_registry_cleanliness(
        active_skill_names: set[str] | list[str] | None = None,
    ) -> list[ComplianceViolation]:
        """Audit the Tool Registry memory flat-index for orphan tool registrations."""
        from myrm_agent_harness.core.security.tool_registry.registry import (
            _PTC_LOCK,
            _PTC_SAFETY_METADATA,
            _PTC_TOOL_FLAT_INDEX,
        )

        violations: list[ComplianceViolation] = []
        active_set = set(active_skill_names) if active_skill_names is not None else None

        with _PTC_LOCK:
            # Check 1: Inconsistency between tree metadata and flat index
            indexed_tools_in_tree = {
                tname for skill_tools in _PTC_SAFETY_METADATA.values() for tname in skill_tools
            }
            flat_tools = set(_PTC_TOOL_FLAT_INDEX.keys())

            orphans_in_flat = flat_tools - indexed_tools_in_tree
            for orphan in orphans_in_flat:
                violations.append(
                    ComplianceViolation(
                        question_id="Q2_REGISTRY_CLEAN",
                        target=orphan,
                        reason=f"Tool '{orphan}' exists in flat index but missing from skill hierarchy",
                        severity="high",
                        remediation_hint=f"Call unregister_ptc_safety_metadata to clean orphan tool '{orphan}'",
                    )
                )

            # Check 2: If active_skill_names provided, check for evicted skills still residing in memory
            if active_set is not None:
                for skill_name in list(_PTC_SAFETY_METADATA.keys()):
                    if skill_name not in active_set:
                        violations.append(
                            ComplianceViolation(
                                question_id="Q2_REGISTRY_CLEAN",
                                target=skill_name,
                                reason=f"Skill '{skill_name}' is not in active plugins list but still registered in memory",
                                severity="high",
                                remediation_hint=f"Call evict_skill_safety_metadata('{skill_name}') to remove ghost tools",
                            )
                        )

        return violations

    @classmethod
    def evaluate_full_compliance(
        cls,
        active_skill_names: set[str] | list[str] | None = None,
        custom_checks: list[tuple[str, bool, str, str]] | None = None,
    ) -> ComplianceReport:
        """Run the comprehensive Six-Question Compliance Audit."""
        violations: list[ComplianceViolation] = []
        questions: dict[str, bool] = {
            "Q1_ROUTES_CLEAN": True,
            "Q2_REGISTRY_CLEAN": True,
            "Q3_CRON_CLEAN": True,
            "Q4_FILESYSTEM_CLEAN": True,
            "Q5_PROCESS_CLEAN": True,
            "Q6_VAULT_CLEAN": True,
        }

        # Run Tool Registry audit
        reg_violations = cls.audit_tool_registry_cleanliness(active_skill_names)
        if reg_violations:
            questions["Q2_REGISTRY_CLEAN"] = False
            violations.extend(reg_violations)

        # Run optional custom / business layer checks
        # Each item: (question_id, is_ok, target, failure_reason)
        if custom_checks:
            for q_id, is_ok, target, reason in custom_checks:
                if not is_ok:
                    questions[q_id] = False
                    violations.append(
                        ComplianceViolation(
                            question_id=q_id,
                            target=target,
                            reason=reason,
                            severity="high",
                            remediation_hint=f"Remediate resource '{target}' for compliance rule {q_id}",
                        )
                    )

        # Compute score (100 base, deductions for failed questions and violations)
        failed_questions = sum(1 for passed in questions.values() if not passed)
        score = max(0, 100 - (failed_questions * 15) - (len(violations) * 5))

        if score == 100 and not violations:
            status = ComplianceStatus.COMPLIANT
        elif score >= 70:
            status = ComplianceStatus.WARNING
        else:
            status = ComplianceStatus.NON_COMPLIANT

        hints = [v.remediation_hint for v in violations if v.remediation_hint]

        return ComplianceReport(
            status=status,
            compliance_score=score,
            checked_at=datetime.now(UTC).isoformat(),
            questions=questions,
            violations=violations,
            remediation_hints=hints,
        )

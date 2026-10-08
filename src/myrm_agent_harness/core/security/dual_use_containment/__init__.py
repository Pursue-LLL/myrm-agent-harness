"""Dual-use skill containment and artifact exfiltration shield suite.

Exports high-level security containment suite and underlying components.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from .exfiltration_shield import ArtifactExfiltrationShield
from .flight_recorder import FlightRecorderEntry, SecurityFlightRecorder
from .ttp_tagger import DualUseTtpTagger
from .types import (
    ArtifactExfiltrationAudit,
    ArtifactSecurityClassification,
    DualUseExecutionGateResult,
    EgressDestinationTrust,
    ExecutionGateRequest,
    MitreAttackTactic,
    SkillSensitivityLevel,
    SkillTtpTagSpec,
)


class DualUseSkillContainmentSuite:
    """Enterprise-grade security gate for isolating dual-use offensive skills and shielding artifacts."""

    def __init__(self, allowlisted_destinations: Sequence[str] | None = None) -> None:
        self.tagger = DualUseTtpTagger()
        self.shield = ArtifactExfiltrationShield(allowlisted_destinations=allowlisted_destinations)
        self.flight_recorder = SecurityFlightRecorder()

    def evaluate_skill_ttp(
        self,
        skill_name: str,
        description: str = "",
        command_signatures: list[str] | None = None,
    ) -> SkillTtpTagSpec:
        """Classify skill by MITRE ATT&CK tactics and quarantine constraints."""
        return self.tagger.evaluate_skill(
            skill_name=skill_name,
            description=description,
            command_signatures=command_signatures,
        )

    def check_execution_gate(self, request: ExecutionGateRequest) -> DualUseExecutionGateResult:
        """Evaluate pre-execution constraints: sandbox quarantine pod & mandatory HITL confirmation."""
        ttp_spec = self.tagger.evaluate_skill(
            skill_name=request.skill_name,
            description=request.command_line,
        )

        event_id = f"evt_{uuid.uuid4().hex[:12]}"

        # 1. Benign skill
        if ttp_spec.sensitivity_level == SkillSensitivityLevel.BENIGN:
            self.flight_recorder.record_event(
                entry_id=event_id,
                event_type="skill_gate_evaluation",
                subject=request.skill_name,
                decision="permitted",
                details={"tactic_count": 0, "quarantine": False},
            )
            return DualUseExecutionGateResult(
                permitted=True,
                requires_hitl_modal=False,
                sensitivity_level=SkillSensitivityLevel.BENIGN,
                enforce_quarantine_pod=False,
                reason="Benign skill approved for standard execution.",
                matched_tactics=[],
            )

        # 2. Dual-use sensitive skill: must be in quarantine pod
        if not request.is_running_in_quarantine_pod:
            self.flight_recorder.record_event(
                entry_id=event_id,
                event_type="skill_gate_evaluation",
                subject=request.skill_name,
                decision="blocked",
                details={"reason": "quarantine_pod_missing"},
            )
            return DualUseExecutionGateResult(
                permitted=False,
                requires_hitl_modal=False,
                sensitivity_level=SkillSensitivityLevel.DUAL_USE_SENSITIVE,
                enforce_quarantine_pod=True,
                reason=(
                    f"Blocked: Skill '{request.skill_name}' exhibits dual-use offensive capabilities "
                    f"and is strictly prohibited from running on native host. Must run in quarantine pod."
                ),
                matched_tactics=ttp_spec.tactics,
            )

        # 3. Dual-use sensitive skill: requires explicit HITL approval token
        if not request.approval_token or not request.approval_token.startswith("hitl_approved_"):
            warning_msg = (
                f"⚠️ 高危攻防指令警示：技能 '{request.skill_name}' 匹配 ATT&CK 战术 "
                f"{[t.value for t in ttp_spec.tactics]}。目标: {request.target_host_or_ip}。需人类显式物理确认。"
            )
            self.flight_recorder.record_event(
                entry_id=event_id,
                event_type="skill_gate_evaluation",
                subject=request.skill_name,
                decision="requires_hitl",
                details={"target": request.target_host_or_ip, "tactics": len(ttp_spec.tactics)},
            )
            return DualUseExecutionGateResult(
                permitted=False,
                requires_hitl_modal=True,
                sensitivity_level=SkillSensitivityLevel.DUAL_USE_SENSITIVE,
                enforce_quarantine_pod=True,
                reason="Dual-use offensive action requires human-in-the-loop physical confirmation.",
                matched_tactics=ttp_spec.tactics,
                hitl_prompt_warning=warning_msg,
            )

        # 4. Approved in quarantine pod with valid HITL token
        self.flight_recorder.record_event(
            entry_id=event_id,
            event_type="skill_gate_evaluation",
            subject=request.skill_name,
            decision="permitted",
            details={"approved": True, "quarantine_pod": True},
        )
        return DualUseExecutionGateResult(
            permitted=True,
            requires_hitl_modal=False,
            sensitivity_level=SkillSensitivityLevel.DUAL_USE_SENSITIVE,
            enforce_quarantine_pod=True,
            reason="Dual-use action approved by human operator in quarantine pod.",
            matched_tactics=ttp_spec.tactics,
        )

    def evaluate_artifact_egress(
        self,
        artifact_id: str,
        artifact_name: str,
        content_bytes: bytes,
        target_destination: str,
        explicit_classification: ArtifactSecurityClassification | None = None,
    ) -> ArtifactExfiltrationAudit:
        """Intercept and inspect artifact egress attempts."""
        audit = self.shield.evaluate_egress(
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            content_bytes=content_bytes,
            target_destination=target_destination,
            explicit_classification=explicit_classification,
        )

        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        decision = "blocked" if audit.is_blocked else "permitted"
        self.flight_recorder.record_event(
            entry_id=event_id,
            event_type="artifact_egress_shield",
            subject=artifact_name,
            decision=decision,
            details={"destination": target_destination, "blocked": audit.is_blocked},
        )
        return audit

    def get_flight_recorder_logs(self, limit: int = 50) -> list[FlightRecorderEntry]:
        """Fetch audit trail events from flight recorder."""
        return self.flight_recorder.get_recent_entries(limit=limit)


__all__ = [
    "ArtifactExfiltrationAudit",
    "ArtifactExfiltrationShield",
    "ArtifactSecurityClassification",
    "DualUseExecutionGateResult",
    "DualUseSkillContainmentSuite",
    "DualUseTtpTagger",
    "EgressDestinationTrust",
    "ExecutionGateRequest",
    "FlightRecorderEntry",
    "MitreAttackTactic",
    "SecurityFlightRecorder",
    "SkillSensitivityLevel",
    "SkillTtpTagSpec",
]

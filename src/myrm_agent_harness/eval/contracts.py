"""Five-Contract Delivery Lifecycle Protocol & Verification State Machine.

[INPUT]
- protocols::EvalCase, AgentResponse, EvalTurnResult (POS: evaluation trajectory & turn contracts)

[OUTPUT]
- DeliveryContractPhase: canonical 5-phase delivery contract enum
  (TASK_INTENT, SCENE_ENVIRONMENT, ACTION_EXECUTION, DELIVERY_ARTIFACT, ACCEPTANCE_VERIFICATION)
- ContractStatus: lifecycle status per phase (PENDING, IN_PROGRESS, SATISFIED, VIOLATED, WAITING_APPROVAL)
- PhaseContractRecord: structured status, evidence, and audit logs per contract phase
- FiveContractStateSnapshot: full 5-contract progress snapshot for trajectory auditing & UI rendering
- evaluate_five_contract_progress(): deterministic validator for agent delivery state machine

[POS]
Provides standardized contract lifecycle governance across complex multi-step agent workflows.
Eliminates black-box waiting by structuring task progression into 5 transparent engineering phases
aligned with Article 15 (Intent Alignment -> Plan/Action Execution -> Artifact Delivery & Acceptance).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class DeliveryContractPhase(enum.StrEnum):
    """Canonical 5-contract delivery lifecycle phases."""

    TASK_INTENT = "task_intent"  # 1. 任务意图与范围对齐
    SCENE_ENVIRONMENT = "scene_environment"  # 2. 现场依赖、权限与沙箱环境准备
    ACTION_EXECUTION = "action_execution"  # 3. 规划步骤执行与工具调用
    DELIVERY_ARTIFACT = "delivery_artifact"  # 4. 交付物生成与变更产出
    ACCEPTANCE_VERIFICATION = "acceptance_verification"  # 5. 验收测试、语法检查与事实核验


class ContractStatus(enum.StrEnum):
    """Lifecycle status for an individual delivery contract."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    WAITING_APPROVAL = "waiting_approval"


@dataclass(frozen=True, slots=True)
class PhaseContractRecord:
    """Status record and evidence for a specific delivery contract phase."""

    phase: DeliveryContractPhase
    status: ContractStatus
    summary: str
    evidence: list[str] = field(default_factory=list)
    progress_pct: int = 0  # 0 to 100
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "status": self.status.value,
            "summary": self.summary,
            "evidence": list(self.evidence),
            "progress_pct": self.progress_pct,
            "details": self.details,
        }


@dataclass(slots=True)
class FiveContractStateSnapshot:
    """Full snapshot of the 5-contract delivery lifecycle for a workflow or session."""

    contracts: dict[str, PhaseContractRecord] = field(default_factory=dict)
    current_phase: DeliveryContractPhase = DeliveryContractPhase.TASK_INTENT
    overall_progress_pct: int = 0
    is_fully_satisfied: bool = False
    has_violations: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "contracts": {k: v.to_dict() for k, v in self.contracts.items()},
            "current_phase": self.current_phase.value,
            "overall_progress_pct": self.overall_progress_pct,
            "is_fully_satisfied": self.is_fully_satisfied,
            "has_violations": self.has_violations,
        }


def build_initial_five_contract_state(task_intent_summary: str = "Aligning user objective") -> FiveContractStateSnapshot:
    """Construct an initial clean 5-contract state machine snapshot."""
    contracts: dict[str, PhaseContractRecord] = {
        DeliveryContractPhase.TASK_INTENT.value: PhaseContractRecord(
            phase=DeliveryContractPhase.TASK_INTENT,
            status=ContractStatus.IN_PROGRESS,
            summary=task_intent_summary,
            progress_pct=50,
        ),
        DeliveryContractPhase.SCENE_ENVIRONMENT.value: PhaseContractRecord(
            phase=DeliveryContractPhase.SCENE_ENVIRONMENT,
            status=ContractStatus.PENDING,
            summary="Pending environment setup",
            progress_pct=0,
        ),
        DeliveryContractPhase.ACTION_EXECUTION.value: PhaseContractRecord(
            phase=DeliveryContractPhase.ACTION_EXECUTION,
            status=ContractStatus.PENDING,
            summary="Pending tool action execution",
            progress_pct=0,
        ),
        DeliveryContractPhase.DELIVERY_ARTIFACT.value: PhaseContractRecord(
            phase=DeliveryContractPhase.DELIVERY_ARTIFACT,
            status=ContractStatus.PENDING,
            summary="Pending artifact creation",
            progress_pct=0,
        ),
        DeliveryContractPhase.ACCEPTANCE_VERIFICATION.value: PhaseContractRecord(
            phase=DeliveryContractPhase.ACCEPTANCE_VERIFICATION,
            status=ContractStatus.PENDING,
            summary="Pending test and proof verification",
            progress_pct=0,
        ),
    }
    return FiveContractStateSnapshot(
        contracts=contracts,
        current_phase=DeliveryContractPhase.TASK_INTENT,
        overall_progress_pct=10,
        is_fully_satisfied=False,
        has_violations=False,
    )


def evaluate_five_contract_progress(
    *,
    has_user_intent: bool = True,
    workspace_ready: bool = True,
    tool_calls_count: int = 0,
    has_artifacts_produced: bool = False,
    test_verification_passed: bool | None = None,
    execution_error: str | None = None,
) -> FiveContractStateSnapshot:
    """Evaluate and transition the 5-contract state machine based on execution milestones."""
    contracts: dict[str, PhaseContractRecord] = {}
    current_phase = DeliveryContractPhase.TASK_INTENT
    has_violations = False

    # 1. Task Intent Contract
    if has_user_intent:
        c1 = PhaseContractRecord(
            phase=DeliveryContractPhase.TASK_INTENT,
            status=ContractStatus.SATISFIED,
            summary="Objective and constraints validated",
            progress_pct=100,
        )
    else:
        c1 = PhaseContractRecord(
            phase=DeliveryContractPhase.TASK_INTENT,
            status=ContractStatus.IN_PROGRESS,
            summary="Clarifying task parameters",
            progress_pct=40,
        )
    contracts[DeliveryContractPhase.TASK_INTENT.value] = c1

    # 2. Scene Environment Contract
    if not workspace_ready:
        c2 = PhaseContractRecord(
            phase=DeliveryContractPhase.SCENE_ENVIRONMENT,
            status=ContractStatus.VIOLATED if execution_error else ContractStatus.IN_PROGRESS,
            summary=f"Workspace initialization error: {execution_error}" if execution_error else "Mounting sandbox & tools",
            progress_pct=30,
        )
        current_phase = DeliveryContractPhase.SCENE_ENVIRONMENT
        if execution_error:
            has_violations = True
    else:
        c2 = PhaseContractRecord(
            phase=DeliveryContractPhase.SCENE_ENVIRONMENT,
            status=ContractStatus.SATISFIED,
            summary="Sandbox, tools, and credentials ready",
            progress_pct=100,
        )
    contracts[DeliveryContractPhase.SCENE_ENVIRONMENT.value] = c2

    # 3. Action Execution Contract
    if tool_calls_count > 0:
        if execution_error and test_verification_passed is False:
            c3 = PhaseContractRecord(
                phase=DeliveryContractPhase.ACTION_EXECUTION,
                status=ContractStatus.VIOLATED,
                summary=f"Action interrupted: {execution_error}",
                progress_pct=70,
                evidence=[f"tool_calls={tool_calls_count}"],
            )
            current_phase = DeliveryContractPhase.ACTION_EXECUTION
            has_violations = True
        else:
            c3 = PhaseContractRecord(
                phase=DeliveryContractPhase.ACTION_EXECUTION,
                status=ContractStatus.SATISFIED if has_artifacts_produced else ContractStatus.IN_PROGRESS,
                summary=f"Executed {tool_calls_count} action(s)",
                progress_pct=100 if has_artifacts_produced else 80,
                evidence=[f"tool_calls={tool_calls_count}"],
            )
            if not has_artifacts_produced:
                current_phase = DeliveryContractPhase.ACTION_EXECUTION
    else:
        c3 = PhaseContractRecord(
            phase=DeliveryContractPhase.ACTION_EXECUTION,
            status=ContractStatus.PENDING,
            summary="Awaiting tool call dispatch",
            progress_pct=0,
        )
        if workspace_ready and has_user_intent:
            current_phase = DeliveryContractPhase.ACTION_EXECUTION
    contracts[DeliveryContractPhase.ACTION_EXECUTION.value] = c3

    # 4. Delivery Artifact Contract
    if has_artifacts_produced:
        c4 = PhaseContractRecord(
            phase=DeliveryContractPhase.DELIVERY_ARTIFACT,
            status=ContractStatus.SATISFIED,
            summary="Generated deliverables and changes",
            progress_pct=100,
        )
    else:
        c4 = PhaseContractRecord(
            phase=DeliveryContractPhase.DELIVERY_ARTIFACT,
            status=ContractStatus.PENDING if tool_calls_count == 0 else ContractStatus.IN_PROGRESS,
            summary="Constructing output artifacts",
            progress_pct=30 if tool_calls_count > 0 else 0,
        )
        if tool_calls_count > 0 and current_phase == DeliveryContractPhase.TASK_INTENT:
            current_phase = DeliveryContractPhase.DELIVERY_ARTIFACT
    contracts[DeliveryContractPhase.DELIVERY_ARTIFACT.value] = c4

    # 5. Acceptance Verification Contract
    if test_verification_passed is True:
        c5 = PhaseContractRecord(
            phase=DeliveryContractPhase.ACCEPTANCE_VERIFICATION,
            status=ContractStatus.SATISFIED,
            summary="All automated tests and assertions passed",
            progress_pct=100,
        )
        current_phase = DeliveryContractPhase.ACCEPTANCE_VERIFICATION
    elif test_verification_passed is False:
        c5 = PhaseContractRecord(
            phase=DeliveryContractPhase.ACCEPTANCE_VERIFICATION,
            status=ContractStatus.VIOLATED,
            summary=f"Verification failed: {execution_error or 'Assertion defect found'}",
            progress_pct=60,
        )
        current_phase = DeliveryContractPhase.ACCEPTANCE_VERIFICATION
        has_violations = True
    else:
        c5 = PhaseContractRecord(
            phase=DeliveryContractPhase.ACCEPTANCE_VERIFICATION,
            status=ContractStatus.PENDING,
            summary="Awaiting test suite evaluation",
            progress_pct=0,
        )
        if has_artifacts_produced:
            current_phase = DeliveryContractPhase.ACCEPTANCE_VERIFICATION
    contracts[DeliveryContractPhase.ACCEPTANCE_VERIFICATION.value] = c5

    # Overall percentage
    total_pct = sum(r.progress_pct for r in contracts.values())
    overall_progress_pct = total_pct // 5
    is_fully_satisfied = all(r.status == ContractStatus.SATISFIED for r in contracts.values())

    return FiveContractStateSnapshot(
        contracts=contracts,
        current_phase=current_phase,
        overall_progress_pct=overall_progress_pct,
        is_fully_satisfied=is_fully_satisfied,
        has_violations=has_violations,
    )

"""
[INPUT]: Task specs, agent personas, execution traces, test verification exit codes, and user reviews.
[OUTPUT]: Immutable DeliveryEvidenceDossier, verification receipts, and stratified AssetFrictionMetric models.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/delivery_dossier/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class UserAcceptanceStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    PARTIALLY_MODIFIED = "PARTIALLY_MODIFIED"
    REJECTED_REWORK = "REJECTED_REWORK"


class ExecutionMode(str, Enum):
    SINGLE_SHOT = "SINGLE_SHOT"
    MULTI_TURN_AGENT = "MULTI_TURN_AGENT"


class AssetHealthTag(str, Enum):
    CORE_EFFICIENT = "CORE_EFFICIENT"  # 🌟 核心高效资产
    NORMAL = "NORMAL"
    FRICTION_ASSASSIN = "FRICTION_ASSASSIN"  # ⚠️ 摩擦刺客资产
    SAMPLE_INSUFFICIENT = "SAMPLE_INSUFFICIENT"  # 样本不足


@dataclass(frozen=True)
class TaskSpecRecord:
    task_goal: str
    acceptance_criteria: List[str]
    non_goals: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentPersonaFingerprint:
    agent_id: str
    model_name: str
    prompt_hash: str
    mounted_skills: List[str]


@dataclass(frozen=True)
class ToolExecutionTraceItem:
    tool_name: str
    arguments_summary: str
    duration_ms: float
    exit_code: int
    error_message: Optional[str] = None


@dataclass(frozen=True)
class PhysicalVerificationReceipt:
    test_suite_exit_code: int
    passed_tests_count: int
    failed_tests_count: int
    artifact_path: str
    artifact_sha256: str
    verified_at: str


@dataclass(frozen=True)
class DeliveryEvidenceDossier:
    dossier_id: str
    task_id: str
    execution_mode: ExecutionMode
    spec: TaskSpecRecord
    persona: AgentPersonaFingerprint
    tool_traces: List[ToolExecutionTraceItem]
    verification: PhysicalVerificationReceipt
    acceptance: UserAcceptanceStatus
    total_tokens_consumed: int
    wasted_friction_tokens: int
    rework_count: int
    dossier_checksum_sha256: str
    created_at: str


@dataclass(frozen=True)
class AssetFrictionMetric:
    skill_id: str
    model_name: str
    execution_mode: ExecutionMode
    sample_count: int
    true_efficacy_rate_pct: float
    friction_index: float
    total_wasted_tokens: int
    rework_count: int
    retry_count: int
    health_tag: AssetHealthTag
    governance_advice: str

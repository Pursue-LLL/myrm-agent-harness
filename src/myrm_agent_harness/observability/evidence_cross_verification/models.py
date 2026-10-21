"""[INPUT] Multi-source verification artifacts (KB, code symbols, source logic, runtime telemetry).
[OUTPUT] Immutable data structures for 4-tier confidence scoring and root-cause evidence verification.
[POS] myrm_agent_harness.observability.evidence_cross_verification.models

Defines the core data models for multi-source evidence cross-verification:
1. Four evidence source categories (KB, Code, Logic, Runtime)
2. Four-tier confidence classification (High, Medium, Low)
3. Action-oriented root-cause diagnosis finding with patch recommendations
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class EvidenceSourceType(str, Enum):
    """Categorized source origin of an investigative evidence item."""

    KNOWLEDGE_BASE = "KNOWLEDGE_BASE"
    CODE_SYMBOL = "CODE_SYMBOL"
    SOURCE_LOGIC = "SOURCE_LOGIC"
    RUNTIME_TELEMETRY = "RUNTIME_TELEMETRY"


class ConfidenceLevel(str, Enum):
    """Four-tier quantified confidence level based on multi-source proof."""

    HIGH = "HIGH"        # 3~4 points: Definite proof, deliverable patch recommended
    MEDIUM = "MEDIUM"    # 2 points: Partial proof, human operator review required
    LOW = "LOW"          # 0~1 point: Inconclusive proof, archived for telemetry only


@dataclass(frozen=True)
class EvidenceItem:
    """Individual verification fact collected from one diagnostic channel."""

    source_type: EvidenceSourceType
    title: str
    detail: str
    is_verified: bool
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    weight: float = 1.0
    file_path: str = ""
    line_number: int = 0
    trace_id: str = ""

    def to_dict(self) -> dict[str, str | int | float | bool]:
        return {
            "source_type": self.source_type.value,
            "title": self.title,
            "detail": self.detail,
            "is_verified": self.is_verified,
            "timestamp_ms": self.timestamp_ms,
            "weight": self.weight,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True)
class VerificationFinding:
    """Structured, action-oriented root cause diagnosis with quantified confidence."""

    diagnosis_id: str
    error_code: str
    resolved_code_meaning: str
    target_file_path: str
    target_line_number: int
    root_cause_category: str
    explanation: str
    recommended_patch: str
    confidence_score: int
    confidence_level: ConfidenceLevel
    evidences: tuple[EvidenceItem, ...]
    bilateral_verified: bool
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | int | bool | list[dict[str, str | int | float | bool]]]:
        return {
            "diagnosis_id": self.diagnosis_id,
            "error_code": self.error_code,
            "resolved_code_meaning": self.resolved_code_meaning,
            "target_file_path": self.target_file_path,
            "target_line_number": self.target_line_number,
            "root_cause_category": self.root_cause_category,
            "explanation": self.explanation,
            "recommended_patch": self.recommended_patch,
            "confidence_score": self.confidence_score,
            "confidence_level": self.confidence_level.value,
            "evidences": [e.to_dict() for e in self.evidences],
            "bilateral_verified": self.bilateral_verified,
            "created_at_ms": self.created_at_ms,
        }


@dataclass(frozen=True)
class VerificationDiagnosisRequest:
    """Investigative input requiring cross-verification across code and telemetry."""

    error_code: str
    event_date: str  # Format: YYYY-MM-DD
    caller_trace_id: str
    raw_symptom: str
    kb_doc_hint: str = ""
    code_def_hint: str = ""
    call_budget: int = 15  # Default budget to prevent runaway searches

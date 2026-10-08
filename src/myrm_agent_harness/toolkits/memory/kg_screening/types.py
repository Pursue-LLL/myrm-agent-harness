"""Type definitions for knowledge graph pre-extraction content screening and prompt injection shield.

[INPUT]
- enum.StrEnum
- time
- pydantic.BaseModel, ConfigDict, Field

[OUTPUT]
- ScreeningVerdict: Classification outcome (CLEAN, SANITIZED, POISON_BLOCKED)
- ThreatCategory: Detected threat taxonomy
- ThreatFinding: Individual detected threat detail
- ScreeningResult: Comprehensive evaluation report for input text
- ScreeningAuditRecord: Persistent security audit entry for tracking poisoning attempts

[POS]
Core contracts for graph memory extraction compliance, HTML instruction stripping, and anti-poisoning safeguards.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ScreeningVerdict(StrEnum):
    """Evaluation verdict for text candidate before graph extraction."""

    CLEAN = "clean"
    SANITIZED = "sanitized"
    POISON_BLOCKED = "poison_blocked"


class ThreatCategory(StrEnum):
    """Taxonomy of prompt injection and memory poisoning vectors."""

    HIDDEN_HTML_INSTRUCTION = "hidden_html_instruction"
    SYSTEM_PROMPT_OVERRIDE = "system_prompt_override"
    ZERO_WIDTH_CHARACTER = "zero_width_character"
    DATA_EXFILTRATION_PATTERN = "data_exfiltration_pattern"
    UNTRUSTED_INJECTION_DIRECTIVE = "untrusted_injection_directive"


class ThreatFinding(BaseModel):
    """Specific threat or instruction anomaly detected in candidate text."""

    model_config = ConfigDict(extra="forbid")

    category: ThreatCategory = Field(..., description="Classification category of the detected vector")
    matched_pattern: str = Field(..., description="Name or regex descriptor of the matched pattern")
    snippet: str = Field(..., description="Excerpt of suspect text causing the match")
    position: int = Field(ge=0, description="Character offset where finding was identified")
    risk_level: str = Field(..., description="Severity level: 'high' (block) or 'medium'/'low' (sanitizable)")
    description: str = Field(..., description="Human-readable explanation of why this was flagged")


class ScreeningResult(BaseModel):
    """Full outcome report of pre-extraction content screening."""

    model_config = ConfigDict(extra="forbid")

    verdict: ScreeningVerdict = Field(..., description="Overall screening verdict")
    is_blocked: bool = Field(..., description="True if text cannot be safely extracted into graph")
    findings: list[ThreatFinding] = Field(default_factory=list, description="All identified threat vectors")
    original_length: int = Field(ge=0, description="Character count of input text")
    sanitized_content: str = Field(..., description="Cleaned content ready for triple extraction if not blocked")
    risk_score: float = Field(ge=0.0, le=1.0, description="Aggregated risk score (0.0=safe, 1.0=critical poisoning)")


class ScreeningAuditRecord(BaseModel):
    """Historical audit entry recording screening actions and blocked injection attempts."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(..., description="Unique audit record identifier")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp of detection event")
    source_uri: str = Field(default="", description="Origin URI, file path, or tool source if known")
    verdict: ScreeningVerdict = Field(..., description="Screening outcome")
    risk_score: float = Field(ge=0.0, le=1.0, description="Calculated risk score")
    findings_count: int = Field(ge=0, description="Total count of flagged anomalies")
    findings_summary: list[str] = Field(default_factory=list, description="Summary descriptions of findings")
    sanitized_applied: bool = Field(default=False, description="Whether content was stripped and sanitized")

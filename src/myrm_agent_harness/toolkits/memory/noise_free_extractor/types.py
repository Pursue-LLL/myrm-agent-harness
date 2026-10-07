"""[POS]: src/myrm_agent_harness/toolkits/memory/noise_free_extractor/types.py
[INPUT]: Raw conversation turn dictionaries, PII violation rules, and epoch configurations.
[OUTPUT]: Pydantic and dataclass contracts for sanitized messages, candidates, and epoch statuses.

Reference: Anthropic Commerce Agents (commerce_common/memory.py).
Provides structured definitions for tool-stripped conversation turns, PII safety violations,
and monotonic epoch fencing for async memory extraction.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    """Raw conversation turn containing potential tool calls and receipts."""

    role: Literal["user", "assistant", "tool", "system"] = Field(
        ..., description="Message author role."
    )
    content: str = Field(..., description="Message text or payload body.")
    tool_calls: list[dict[str, str]] | None = Field(
        default=None, description="Optional raw tool calls invoked by assistant."
    )
    tool_call_id: str | None = Field(
        default=None, description="Identifier for tool execution output."
    )


class ToolStrippedMessage(BaseModel):
    """Pure conversation message with all external tool outputs and noise stripped."""

    role: Literal["user", "assistant", "system"] = Field(
        ..., description="Clean conversational role."
    )
    clean_text: str = Field(..., description="Noise-free textual content.")
    stripped_tokens_est: int = Field(
        default=0, description="Estimated token count omitted from tool receipts."
    )


class PIIViolationDetail(BaseModel):
    """Details of a blocked PII pattern detection."""

    rule_name: str = Field(..., description="Identified PII rule name.")
    snippet_masked: str = Field(
        ..., description="Masked snippet indicating location of sensitive data."
    )
    severity: Literal["high", "critical", "medium"] = Field(
        default="critical", description="Risk level."
    )


class SanitizedExtractionResult(BaseModel):
    """Result of PII inspection on extracted candidate text."""

    is_clean: bool = Field(..., description="Whether candidate passed all PII checks.")
    sanitized_text: str = Field(
        ..., description="Sanitized or masked text safe for storage."
    )
    violations: list[PIIViolationDetail] = Field(
        default_factory=list, description="Detected violations if any."
    )


class ExtractedFactCandidate(BaseModel):
    """Candidate memory fact ready for epoch validation and persistence."""

    fact_id: str = Field(..., description="Unique fact candidate identifier.")
    fact_text: str = Field(..., description="Extracted memory fact statement.")
    category: str = Field(default="user_preference", description="Memory classification.")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0, description="Extraction confidence.")
    generation_observed: int = Field(
        ..., description="Generation index observed when extraction task started."
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Candidate timestamp.",
    )


@dataclass
class PurgeEpochStatus:
    """Status record of a user's purge generation and asynchronous epoch health."""

    user_id: str
    current_generation: int
    active_extractions: int = 0
    stale_writes_dropped: int = 0
    last_purged_at: str | None = None
    stored_facts_count: int = 0
    pii_violations_blocked: int = 0


@dataclass
class NoiseFreeConfig:
    """Configuration for noise stripping and PII guardrails."""

    strip_tool_receipts: bool = True
    enforce_pii_gate: bool = True
    mask_pii_instead_of_reject: bool = False
    min_confidence_threshold: float = 0.75
    blocked_patterns: list[str] = field(
        default_factory=lambda: [
            "credit_card",
            "iban",
            "ssn_national_id",
            "secret_token_key",
            "restricted_email",
        ]
    )

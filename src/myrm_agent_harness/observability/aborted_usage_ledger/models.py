"""
[INPUT]: Token usage records, provider call statuses, auxiliary kinds, and availability metadata.
[OUTPUT]: Strongly typed models for canonical usage ledger rows with explicit usage-unknown flags for aborted auxiliary calls.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/aborted_usage_ledger/models.py
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class UsageAvailabilityKind(str, Enum):
    """Availability classification of token usage payload."""

    EXACT = "exact"
    USAGE_UNKNOWN = "usage-unknown"
    ESTIMATED = "estimated"


class LedgerCallStatus(str, Enum):
    """Execution status of model invocation."""

    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AuxiliaryCallKind(str, Enum):
    """Lifecycle kind distinguishing primary conversation from auxiliary tasks."""

    PRIMARY = "primary"
    AUXILIARY_SUMMARY = "auxiliary_summary"
    AUXILIARY_AUDIT = "auxiliary_audit"
    AUXILIARY_ROUTER = "auxiliary_router"
    AUXILIARY_COMPACTION = "auxiliary_compaction"
    AUXILIARY_OTHER = "auxiliary_other"


class CanonicalUsageLedgerRow(BaseModel):
    """Single canonical ledger record preventing pseudo-free zero-token representation on aborted calls."""

    call_id: str = Field(...)
    session_id: str = Field(...)
    task_id: str = Field(...)
    call_kind: AuxiliaryCallKind = Field(default=AuxiliaryCallKind.PRIMARY)
    call_status: LedgerCallStatus = Field(default=LedgerCallStatus.COMPLETED)
    usage_availability: UsageAvailabilityKind = Field(
        default=UsageAvailabilityKind.EXACT,
        description="Explicitly USAGE_UNKNOWN on aborted calls without token report",
    )
    prompt_tokens: Optional[int] = Field(default=None, ge=0)
    completion_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)
    cost_usd: Optional[float] = Field(default=None, ge=0.0)
    provider_raw_status: str = Field(default="")
    timestamp_ms: int = Field(...)


class AbortedUsageUnknownStats(BaseModel):
    """Aggregated ledger statistics partitioning exact usage from unknown aborted calls."""

    total_calls: int = Field(default=0, ge=0)
    known_usage_calls: int = Field(default=0, ge=0)
    unknown_usage_calls: int = Field(default=0, ge=0)
    aborted_calls_count: int = Field(default=0, ge=0)
    total_known_prompt_tokens: int = Field(default=0, ge=0)
    total_known_completion_tokens: int = Field(default=0, ge=0)
    total_known_tokens: int = Field(default=0, ge=0)
    total_known_cost_usd: float = Field(default=0.0, ge=0.0)
    unknown_risk_flag: bool = Field(
        default=False,
        description="True if unbilled/unaccounted aborted auxiliary calls exist",
    )
    timestamp_ms: int = Field(...)

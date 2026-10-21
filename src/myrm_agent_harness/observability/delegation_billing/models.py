"""
[INPUT]: Token counts, delegation source backends, auth modes (subscription vs api_key), and timestamp metadata.
[OUTPUT]: Strongly-typed models for external delegation usage billing transparency and cost divergence.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/delegation_billing/models.py
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DelegationAuthMode(str, Enum):
    """Authentication and billing entitlement mode for external agent delegations."""

    SUBSCRIPTION = "subscription"
    API_KEY = "api_key"


class DelegationUsageRecord(BaseModel):
    """Immutable audit record of an external agent delegation token usage and billing attribution."""

    record_id: str = Field(..., description="Unique record identifier")
    session_id: str = Field(..., description="Parent chat session ID")
    source: str = Field(..., description="Backend delegation source (e.g. delegate:claude, invoke_acp:codex)")
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    auth_mode: DelegationAuthMode = Field(..., description="subscription (zero API bill) vs api_key (metered)")
    billable: bool = Field(..., description="True if this run debited from API quota; False if running on user subscription")
    estimated_savings_usd: float = Field(default=0.0, ge=0.0, description="Estimated dollar savings from user subscription reuse")
    billed_cost_usd: float = Field(default=0.0, ge=0.0, description="Direct API dollar cost billed to user/team ledger")
    timestamp_ms: int = Field(..., description="Execution epoch timestamp in milliseconds")


class DelegationSourceMetric(BaseModel):
    """Aggregate metrics per delegation source backend."""

    source: str = Field(...)
    calls_count: int = Field(default=0, ge=0)
    subscription_tokens: int = Field(default=0, ge=0)
    api_key_tokens: int = Field(default=0, ge=0)
    savings_usd: float = Field(default=0.0, ge=0.0)
    cost_usd: float = Field(default=0.0, ge=0.0)


class DelegationBillingSummary(BaseModel):
    """Cross-session roll-up of external delegation usage and transparent dual-track billing breakdown."""

    total_delegations: int = Field(default=0, ge=0)
    subscription_calls_count: int = Field(default=0, ge=0)
    api_key_calls_count: int = Field(default=0, ge=0)
    total_subscription_tokens: int = Field(default=0, ge=0)
    total_api_key_tokens: int = Field(default=0, ge=0)
    total_estimated_savings_usd: float = Field(default=0.0, ge=0.0)
    total_billed_cost_usd: float = Field(default=0.0, ge=0.0)
    sources: List[DelegationSourceMetric] = Field(default_factory=list)
    timestamp_ms: int = Field(...)

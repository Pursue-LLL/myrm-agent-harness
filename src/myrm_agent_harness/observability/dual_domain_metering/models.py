"""
[INPUT]: Dual-domain operation parameters, 3D cost breakdowns, and reconciliation requests.
[OUTPUT]: Immutable Pydantic models for dual-domain metering specification and penetrating cost ledger.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/dual_domain_metering/models.py
"""

from enum import Enum
import hashlib
import json
from typing import Dict, List
from pydantic import BaseModel, Field


class MeteringDomain(str, Enum):
    """Clear boundary partition between platform gateway and sandboxed execution."""

    GATEWAY_DOMAIN = "gateway_domain"  # Prompt tokens, model routing, streaming ingress/egress
    SANDBOX_DOMAIN = "sandbox_domain"  # Local/remote sandbox compute, code execution, container RAM/CPU


class ThreeDimensionalCost(BaseModel):
    """Three-dimensional penetrating cost attribution."""

    model_token_cost_usd: float = Field(default=0.0, ge=0.0, description="Cost from LLM prompt & completion tokens")
    sandbox_compute_cost_usd: float = Field(default=0.0, ge=0.0, description="Cost from container CPU/RAM seconds")
    thirdparty_tool_cost_usd: float = Field(default=0.0, ge=0.0, description="Cost from external billable APIs / MCP services")

    @property
    def total_cost_usd(self) -> float:
        return round(self.model_token_cost_usd + self.sandbox_compute_cost_usd + self.thirdparty_tool_cost_usd, 6)


class DomainMeteringRecord(BaseModel):
    """Single itemized metering record bounded by gateway or sandbox execution domain."""

    record_id: str = Field(..., description="Unique immutable metering entry ID")
    session_id: str = Field(..., description="Parent agent session ID")
    domain: MeteringDomain = Field(..., description="Gateway or sandbox domain boundary")
    operation_name: str = Field(..., description="e.g. llm_chat_completion, python_script_exec, brave_web_search")
    resource_units: float = Field(..., ge=0.0, description="Tokens count, CPU-seconds, or API request count")
    cost_breakdown: ThreeDimensionalCost = Field(..., description="3D cost attribution breakdown")
    billable: bool = Field(default=True, description="False if execution is covered by flat-rate / local free tier")
    policy_note: str = Field(default="", description="Human-readable metering policy explanation")
    timestamp_ms: int = Field(..., ge=0, description="Epoch timestamp of record")


class SessionDualDomainSummary(BaseModel):
    """Aggregated financial audit summary split across dual domains and 3D dimensions."""

    session_id: str = Field(..., description="Session identifier")
    gateway_token_cost_usd: float = Field(..., ge=0.0)
    sandbox_compute_cost_usd: float = Field(..., ge=0.0)
    thirdparty_tool_cost_usd: float = Field(..., ge=0.0)
    total_cost_usd: float = Field(..., ge=0.0)
    total_operations: int = Field(..., ge=0)
    gateway_ops_count: int = Field(..., ge=0)
    sandbox_ops_count: int = Field(..., ge=0)
    gateway_cost_ratio: float = Field(..., ge=0.0, le=1.0)
    sandbox_cost_ratio: float = Field(..., ge=0.0, le=1.0)
    generated_at_ms: int = Field(..., ge=0)


class ReconciliationStatement(BaseModel):
    """Cryptographically verifiable enterprise financial reconciliation statement."""

    statement_id: str = Field(..., description="Unique statement identifier")
    session_id: str = Field(..., description="Session identifier")
    summary: SessionDualDomainSummary
    records: List[DomainMeteringRecord] = Field(default_factory=list)
    integrity_sha256: str = Field(..., description="SHA-256 hash guaranteeing tamper-proof auditability")
    generated_at_ms: int = Field(..., ge=0)

    @classmethod
    def compute_sha256(cls, session_id: str, summary: SessionDualDomainSummary, records: List[DomainMeteringRecord]) -> str:
        payload = {
            "session_id": session_id,
            "total_cost_usd": summary.total_cost_usd,
            "total_operations": summary.total_operations,
            "records_count": len(records),
            "record_ids": [r.record_id for r in records],
        }
        raw_json = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

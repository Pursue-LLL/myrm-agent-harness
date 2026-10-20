"""[INPUT] Pydantic models and enums for Hermes Fabric remote dispatch and durable journals.
[OUTPUT] Strong types: JournalEntryType, DispatchJournalEntry, WorkContract, EvidenceItem, RecoveryPlan, DispatchReceipt.
[POS] Type definitions for Hermes Fabric remote dispatch durable journal subsystem.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class JournalEntryType(StrEnum):
    """Lifecycle event types recorded into durable journals."""

    DISPATCH_INIT = "dispatch_init"
    PRESTART_POLICY_PASS = "prestart_policy_pass"
    PRESTART_POLICY_FAIL = "prestart_policy_fail"
    DISPATCH_SENT = "dispatch_sent"
    PEER_ACK = "peer_ack"
    EXEC_PROGRESS = "exec_progress"
    EVIDENCE_ADMITTED = "evidence_admitted"
    EVIDENCE_REJECTED = "evidence_rejected"
    TERMINAL_RESOLVED = "terminal_resolved"
    RECOVERY_RESUMED = "recovery_resumed"


class DispatchJournalEntry(BaseModel):
    """An immutable, append-only journal record in the durable ledger."""

    journal_id: str = Field(default_factory=lambda: f"jnl_{uuid.uuid4().hex[:12]}")
    dispatch_id: str = Field(..., description="Unique remote dispatch transaction ID")
    seq: int = Field(..., description="Monotonically increasing sequence number per dispatch")
    entry_type: JournalEntryType = Field(..., description="State transition or evidence event")
    timestamp: float = Field(default_factory=time.time, description="Epoch timestamp of recording")
    payload_hash: str = Field(..., description="SHA-256 digest of payload for tamper detection")
    metadata: dict[str, str] = Field(default_factory=dict, description="Diagnostic key-value context")


class WorkContract(BaseModel):
    """Execution contract governing a deterministic remote dispatch task."""

    dispatch_id: str = Field(default_factory=lambda: f"dsp_{uuid.uuid4().hex[:10]}")
    task_name: str = Field(..., description="Designated subtask identifier")
    target_peer_id: str = Field(..., description="Target worker node or sandbox ID")
    coordinator_principal_id: str = Field(default="coord_primary", description="Authoritative coordinator principal")
    max_budget_tokens: int = Field(default=50000, description="Token allowance for remote worker execution")
    expires_at: float = Field(..., description="Epoch expiration timestamp for contract freshness")
    required_policies: list[str] = Field(
        default_factory=lambda: ["sandbox_isolation", "network_whitelist", "credential_validity"],
        description="List of security policies that must remain valid at pre-start",
    )


class EvidenceItem(BaseModel):
    """Structured evidence item submitted by peer worker."""

    evidence_id: str = Field(default_factory=lambda: f"evi_{uuid.uuid4().hex[:8]}")
    evidence_type: str = Field(..., description="Artifact, execution log, or tool output")
    size_bytes: int = Field(..., ge=0, description="Payload size in bytes")
    content_digest: str = Field(..., description="Content hash of evidence")
    description: str = Field(default="", description="Summary description")
    admitted: bool = Field(default=True, description="Whether evidence conforms to bounds admission")


class DispatchReceipt(BaseModel):
    """Receipt acknowledged by peer worker upon successful dispatch."""

    dispatch_id: str = Field(..., description="Transaction dispatch ID")
    acknowledged_seq: int = Field(..., description="Acknowledged journal sequence number")
    prestart_verified: bool = Field(..., description="Whether pre-start policy was confirmed")
    peer_status: str = Field(default="accepted", description="Status code (accepted / active / complete)")


class RecoveryPlan(BaseModel):
    """Idempotent resume directive computed after a node restart or network drop."""

    dispatch_id: str = Field(..., description="Target dispatch transaction")
    last_known_seq: int = Field(..., description="Last verified journal sequence recorded")
    last_entry_type: JournalEntryType = Field(..., description="Last committed journal phase")
    can_resume: bool = Field(..., description="Whether task state is safe for idempotent continuation")
    resume_action: str = Field(..., description="Action to take: replay_evidence / continue_execution / fail_closed")

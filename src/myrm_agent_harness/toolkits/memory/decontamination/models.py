"""[POS]: src/myrm_agent_harness/toolkits/memory/decontamination/models.py
[INPUT]: Domain primitives and status enumerations for memory provenance and decontamination.
[OUTPUT]: Strongly typed contracts for provenance attestation, decontamination probes, and rollback snapshots.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class ProvenanceSourceKind(StrEnum):
    """Source classification of memory origins."""

    USER_EXPLICIT_INSTRUCTION = "user_explicit_instruction"
    AGENT_REFLECTION_DISTILL = "agent_reflection_distill"
    TOOL_EXECUTION_OBSERVATION = "tool_execution_observation"
    EXTERNAL_WEB_SCRAPE = "external_web_scrape"
    SYSTEM_SYNTHESIS = "system_synthesis"


class DecontaminationStatus(StrEnum):
    """Sanitation verdict status of long-term memory entries."""

    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    QUARANTINED = "quarantined"
    EXPUNGED = "expunged"


class MemoryProvenanceAttestation(BaseModel):
    """Cryptographic provenance voucher certifying memory origin and evidence chain."""

    attestation_id: str = Field(..., description="Unique provenance attestation identifier")
    memory_id: str = Field(..., description="Target memory entry identifier")
    source_kind: ProvenanceSourceKind = Field(..., description="Origin source category")
    session_id: str = Field(..., description="Session identifier where memory originated")
    turn_index: int = Field(default=0, ge=0, description="Exact conversation turn index")
    evidence_snippet: str = Field(default="", description="Verbatim evidence snippet supporting the fact")
    author_identity: str = Field(default="user", description="Identity or role of origin author")
    sha256_signature: str = Field(..., description="HMAC/SHA256 signature guaranteeing provenance authenticity")
    created_at_epoch: float = Field(..., description="Creation epoch timestamp in seconds")


class MemorySnapshotRecord(BaseModel):
    """Lightweight point-in-time memory snapshot descriptor."""

    snapshot_id: str = Field(..., description="Unique snapshot identifier")
    label: str = Field(..., description="Human-readable checkpoint label")
    memory_ids: list[str] = Field(default_factory=list, description="Set of active memory IDs in this snapshot")
    created_at_epoch: float = Field(..., description="Creation epoch timestamp")


class DecontaminationReport(BaseModel):
    """Sanitation evaluation report for a single memory entry."""

    memory_id: str = Field(..., description="Evaluated memory identifier")
    status: DecontaminationStatus = Field(..., description="Determined decontamination status")
    threat_reasons: list[str] = Field(default_factory=list, description="List of detected poisoning indicators")
    evaluated_at_epoch: float = Field(..., description="Evaluation epoch timestamp")


class RollbackReport(BaseModel):
    """Execution report describing a memory rollback or session purge operation."""

    target_id: str = Field(..., description="Target snapshot ID or session ID rolled back")
    label: str = Field(..., description="Operation label or reason")
    quarantined_count: int = Field(default=0, ge=0, description="Number of poisoned memories quarantined")
    restored_count: int = Field(default=0, ge=0, description="Number of baseline memories restored")
    timestamp_epoch: float = Field(..., description="Execution epoch timestamp")

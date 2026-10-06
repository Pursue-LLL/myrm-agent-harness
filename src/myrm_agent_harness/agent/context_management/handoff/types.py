"""Type definitions for cross-agent/cross-session typed handoff protocol.

Defines data contracts for active goal progression, failed approach registries,
implicit constraints, errors & fixes, pending tasks, and exactly-once claim receipts.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class HandoffStatus(StrEnum):
    """Lifecycle states of an agent handoff memorandum."""

    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class FailedApproachRecord(BaseModel):
    """Record of a rejected hypothesis or failed solution route with evidence."""

    model_config = ConfigDict(extra="forbid")

    approach_name: str = Field(..., min_length=1, description="Name or summary of the discarded solution route")
    rejected_reason: str = Field(..., min_length=1, description="Concrete rationale for discarding this approach")
    evidence_snippet: str = Field(default="", description="Verbatim error message, test log, or benchmark snippet")
    attempted_by_profile_id: str | None = Field(default=None, description="Agent profile that attempted the route")


class ImplicitConstraintRecord(BaseModel):
    """Record of non-obvious environmental, architectural, or user constraints."""

    model_config = ConfigDict(extra="forbid")

    scope: str = Field(..., min_length=1, description="Domain or subsystem (e.g. database, sandbox, frontend)")
    constraint_rule: str = Field(..., min_length=1, description="The immutable invariant or rule statement")
    rationale: str = Field(default="", description="Contextual reasoning for this constraint")


class AgentHandoffSpec(BaseModel):
    """Strongly typed multi-agent relay handoff memorandum."""

    model_config = ConfigDict(extra="forbid")

    handoff_id: str = Field(
        default_factory=lambda: f"handoff-{uuid.uuid4().hex[:12]}",
        description="Unique identifier for the handoff protocol packet",
    )
    session_id: str = Field(..., min_length=1, description="Source conversation session identifier")
    source_profile_id: str = Field(..., min_length=1, description="Departing agent profile identifier")
    target_profile_id: str | None = Field(default=None, description="Designated recipient agent profile, or None for any")
    active_goal: str = Field(..., min_length=1, description="Primary mission and currently active milestone")
    failed_approaches: list[FailedApproachRecord] = Field(
        default_factory=list, description="Discarded implementation avenues to prevent looping"
    )
    implicit_constraints: list[ImplicitConstraintRecord] = Field(
        default_factory=list, description="Latent business or runtime restrictions discovered during execution"
    )
    errors_and_fixes: list[str] = Field(
        default_factory=list, description="Discovered pitfalls and corresponding resolution procedures"
    )
    pending_asks: list[str] = Field(
        default_factory=list, description="Unresolved questions, blockers, or items requiring human feedback"
    )
    next_actions: list[str] = Field(
        default_factory=list, description="Sequential immediate action steps for the successor agent"
    )
    status: HandoffStatus = Field(default=HandoffStatus.PENDING, description="Current lifecycle state")
    created_at: float = Field(default_factory=time.time, description="Epoch creation timestamp")
    claimed_at: float | None = Field(default=None, description="Epoch timestamp when claimed by successor")
    claimed_by_profile_id: str | None = Field(default=None, description="Profile ID of the claiming successor agent")
    claimed_by_session_id: str | None = Field(default=None, description="Session ID where handoff was activated")
    completed_at: float | None = Field(default=None, description="Epoch timestamp when successor marked work complete")


class HandoffClaimReceipt(BaseModel):
    """Cryptographic-style receipt proving successful exactly-once claim of handoff."""

    model_config = ConfigDict(extra="forbid")

    handoff_id: str = Field(..., description="ID of the claimed handoff")
    claimed_by_profile_id: str = Field(..., description="Successor agent profile that acquired ownership")
    claimed_by_session_id: str = Field(..., description="Successor session that loaded the context")
    claim_timestamp: float = Field(default_factory=time.time, description="Epoch timestamp of atomic transition")
    handoff_spec: AgentHandoffSpec = Field(..., description="Full handoff snapshot acquired by recipient")


class FinalizeSessionRequest(BaseModel):
    """Payload to finalize an agent session and write durable handoff memorandum."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=1, description="Session to finalize")
    source_profile_id: str = Field(..., min_length=1, description="Current executing agent profile")
    target_profile_id: str | None = Field(default=None, description="Intended successor agent profile")
    active_goal: str = Field(..., min_length=1, description="Active working goal summary")
    failed_approaches: list[FailedApproachRecord] = Field(default_factory=list, description="Discarded approaches")
    implicit_constraints: list[ImplicitConstraintRecord] = Field(default_factory=list, description="Discovered constraints")
    errors_and_fixes: list[str] = Field(default_factory=list, description="Known errors and remedies")
    pending_asks: list[str] = Field(default_factory=list, description="Blockers or pending questions")
    next_actions: list[str] = Field(default_factory=list, description="Next actionable steps")


class FinalizeSessionResult(BaseModel):
    """Result confirmation of durable session finalization and handoff creation."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., description="Finalized session ID")
    handoff_id: str = Field(..., description="Generated durable handoff ID")
    persisted_path: str = Field(..., description="Filesystem storage location of finalized handoff")
    status: HandoffStatus = Field(..., description="Initial state of the handoff packet")
    timestamp: float = Field(default_factory=time.time, description="Finalization epoch timestamp")

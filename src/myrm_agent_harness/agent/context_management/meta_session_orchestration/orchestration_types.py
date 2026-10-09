# [INPUT]: None (Pure domain types and contracts)
# [OUTPUT]: SessionHierarchyType, SessionTrackMode, SubSessionStatus, SubSessionTaskDescriptor, SubSessionProgressCard, DualTrackMemoryEnvelope, SubSessionFailureReport, SubSessionHandoffDigest, MetaSessionConfig
# [POS]: myrm_agent_harness.agent.context_management.meta_session_orchestration.orchestration_types
"""Strongly-typed contracts for Meta-Session Orchestration & Dual-Track Fusion (Item 332).

Defines hierarchical session types, Chat-Cowork dual-track modes, task descriptors,
progress HUD cards, unified memory envelopes, and fault isolation reports.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Final
from pydantic import BaseModel, Field


class SessionHierarchyType(str, Enum):
    """Hierarchy tier of a session in the cascading orchestrator."""

    META = "meta"
    STANDARD = "standard"
    WORKER = "worker"


class SessionTrackMode(str, Enum):
    """Execution track mode for unified memory and lifecycle separation."""

    CHAT = "chat"
    COWORK = "cowork"


class SubSessionStatus(str, Enum):
    """Lifecycle status of a dispatched worker sub-session."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class SubSessionTaskDescriptor(BaseModel):
    """Specification of an orchestrated sub-session dispatched from a meta-session."""

    task_id: str = Field(..., description="Unique sub-session task identifier")
    meta_session_id: str = Field(..., description="Parent meta-session identifier")
    title: str = Field(..., description="Human-readable title of the dispatched sub-task")
    goal_description: str = Field(..., description="Concrete goal and success criteria")
    parameters: dict[str, str | int | float | bool | list[str]] = Field(
        default_factory=dict, description="Structured runtime parameters and environment variables"
    )
    target_track: SessionTrackMode = Field(
        default=SessionTrackMode.COWORK, description="Target execution track mode"
    )
    created_at_iso: str = Field(..., description="Creation UTC timestamp in ISO 8601 format")


class SubSessionProgressCard(BaseModel):
    """Realtime HUD progress card rendered in the parent meta-session."""

    task_id: str = Field(..., description="Sub-session task identifier")
    meta_session_id: str = Field(..., description="Parent meta-session identifier")
    title: str = Field(..., description="Sub-task title")
    status: SubSessionStatus = Field(..., description="Current execution status")
    current_step: str = Field(..., description="Summary of step currently in progress")
    elapsed_seconds: float = Field(0.0, description="Execution duration in seconds")
    tokens_consumed: int = Field(0, description="Tokens consumed by this sub-session")
    completed_substeps: list[str] = Field(
        default_factory=list, description="List of milestone substeps completed so far"
    )
    active_tool: str = Field(
        "", description="Name of the currently executing tool or empty string if idle"
    )
    updated_at_iso: str = Field(..., description="Last progress update UTC timestamp in ISO 8601")


class DualTrackMemoryEnvelope(BaseModel):
    """Unified memory payload bridged seamlessly between Chat and Cowork tracks."""

    envelope_id: str = Field(..., description="Unique memory envelope identifier")
    meta_session_id: str = Field(..., description="Originating or target meta-session identifier")
    track_mode: SessionTrackMode = Field(..., description="Mode that authored this memory envelope")
    user_intent: str = Field(..., description="Core synthesized user goal and scope")
    preferences: dict[str, str] = Field(
        default_factory=dict, description="Extracted user coding and format preferences"
    )
    active_constraints: list[str] = Field(
        default_factory=list, description="Hard constraints and requirements to preserve"
    )
    working_summary: str = Field(
        ..., description="Distilled high-density summary of decisions and context"
    )
    generated_artifacts: list[str] = Field(
        default_factory=list, description="Paths or IDs of artifacts produced in this run"
    )
    envelope_hash: str = Field(
        ..., description="SHA-256 fingerprint ensuring memory envelope integrity"
    )


class SubSessionFailureReport(BaseModel):
    """Isolated fault diagnostic report preventing sub-session errors from crashing meta-session."""

    task_id: str = Field(..., description="Failing sub-session task identifier")
    meta_session_id: str = Field(..., description="Parent meta-session identifier")
    error_type: str = Field(..., description="Classification of the encountered exception")
    error_message: str = Field(..., description="Detailed error description")
    is_isolated: bool = Field(
        True, description="Always True, certifying fault is contained within sub-session"
    )
    suggested_recovery: str = Field(
        ..., description="Recovery strategy: 'retry', 'degrade', or 'parent_takeover'"
    )
    failure_timestamp_iso: str = Field(..., description="Timestamp of failure in ISO 8601")


class SubSessionHandoffDigest(BaseModel):
    """Standardized task delivery brief atomic synthesized into parent meta-session memory."""

    task_id: str = Field(..., description="Completed sub-session identifier")
    meta_session_id: str = Field(..., description="Parent meta-session identifier")
    title: str = Field(..., description="Sub-task title")
    outcome_summary: str = Field(..., description="High-level delivery summary")
    deliverables: list[str] = Field(
        default_factory=list, description="List of created files, endpoints, or PR references"
    )
    lessons_learned: list[str] = Field(
        default_factory=list, description="Key lessons or caveat notes to preserve"
    )
    digest_hash: str = Field(
        ..., description="SHA-256 verification hash of the handoff brief"
    )


class MetaSessionConfig(BaseModel):
    """Configuration governing meta-session cascading orchestration and memory bus."""

    max_concurrent_sub_sessions: int = Field(
        5, description="Maximum simultaneous active sub-sessions per meta-session"
    )
    default_timeout_seconds: float = Field(
        600.0, description="Default timeout duration before a sub-session is marked timed out"
    )
    auto_sink_on_completion: bool = Field(
        True, description="Whether to automatically sink handoff digests to meta memory bus"
    )
    max_retained_cards_per_meta: int = Field(
        50, description="Maximum progress cards kept in active memory per meta-session"
    )


def compute_envelope_hash(
    meta_session_id: str,
    user_intent: str,
    working_summary: str,
    track_mode: SessionTrackMode,
) -> str:
    """Compute SHA-256 fingerprint for a dual-track memory envelope."""
    payload = f"{meta_session_id}::{track_mode.value}::{user_intent}::{working_summary}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_digest_hash(
    task_id: str,
    meta_session_id: str,
    outcome_summary: str,
    deliverables: list[str],
) -> str:
    """Compute SHA-256 fingerprint for a sub-session handoff brief."""
    canonical_deliv = json.dumps(sorted(deliverables), ensure_ascii=False)
    payload = f"{task_id}::{meta_session_id}::{outcome_summary}::{canonical_deliv}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


DEFAULT_MAX_CONCURRENT_SUBSESSIONS: Final[int] = 5
DEFAULT_SUBSESSION_TIMEOUT_SECONDS: Final[float] = 600.0

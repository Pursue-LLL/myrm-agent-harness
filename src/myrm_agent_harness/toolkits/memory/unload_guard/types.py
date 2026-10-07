"""Type definitions for desktop/WebUI unload and graceful flush finalize guard.

Defines schemas for zero-LLM crash-proof emergency snapshot creation and recovery.
Strict typing applied: No `Any` types allowed.

[INPUT]
- External: pydantic

[OUTPUT]
- EmergencySnapshotReason: Reason triggering emergency graceful flush and session finalization.
- EmergencyFlushRequest: Payload submitted when browser page unloads or desktop window closes.
- EmergencyFlushResult: Confirmation output of atomic zero-LLM emergency flush.
- UnfinalizedSessionSummary: Metadata describing an unfinalized session available for startup restoration.

[POS]
Type definitions for desktop/WebUI unload and graceful flush finalize guard.
"""

from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EmergencySnapshotReason(StrEnum):
    """Reason triggering emergency graceful flush and session finalization."""

    BROWSER_UNLOAD = "browser_unload"
    WINDOW_CLOSE_REQUESTED = "window_close_requested"
    SESSION_SWITCH = "session_switch"
    CRASH_PREVENTION = "crash_prevention"


class EmergencyFlushRequest(BaseModel):
    """Payload submitted when browser page unloads or desktop window closes."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=1, description="Active working session identifier")
    active_goal: str = Field(..., min_length=1, description="High-level goal or task description in flight")
    reason: EmergencySnapshotReason = Field(
        default=EmergencySnapshotReason.BROWSER_UNLOAD,
        description="Event reason initiating emergency flush",
    )
    last_tool_call: str | None = Field(default=None, description="Name or summary of the last executed tool")
    modified_files: list[str] = Field(
        default_factory=list, description="List of workspace files modified during session"
    )
    recent_errors: list[str] = Field(
        default_factory=list, description="Recent tool or execution errors encountered"
    )
    next_actions: list[str] = Field(
        default_factory=list, description="Planned next actions left uncompleted"
    )
    unsaved_notes: list[str] = Field(
        default_factory=list, description="Transient notes or scratchpad text from frontend state"
    )
    target_handoff_agent: str | None = Field(
        default=None, description="Designated target agent to resume session"
    )
    source_profile_id: str = Field(default="user-desktop-agent", description="Profile ID of the active agent")


class EmergencyFlushResult(BaseModel):
    """Confirmation output of atomic zero-LLM emergency flush."""

    model_config = ConfigDict(extra="forbid")

    handoff_id: str = Field(..., description="Durable handoff memorandum ID assigned")
    session_id: str = Field(..., description="Session identifier finalized")
    persisted_path: str = Field(..., description="Disk path of the persisted handoff markdown")
    is_zero_llm: bool = Field(default=True, description="True as this snapshot is synthesized without LLM latency")
    summary_markdown: str = Field(..., description="Structured markdown memorandum content")
    created_at: float = Field(default_factory=time.time, description="Timestamp when snapshot was recorded")


class UnfinalizedSessionSummary(BaseModel):
    """Metadata describing an unfinalized session available for startup restoration."""

    model_config = ConfigDict(extra="forbid")

    handoff_id: str = Field(..., description="Handoff record ID")
    session_id: str = Field(..., description="Source session identifier")
    active_goal: str = Field(..., description="Goal recorded in emergency snapshot")
    reason: str = Field(..., description="Trigger reason")
    persisted_path: str = Field(..., description="Storage location of the memorandum")
    created_at: float = Field(..., description="Epoch timestamp when snapshot was written")

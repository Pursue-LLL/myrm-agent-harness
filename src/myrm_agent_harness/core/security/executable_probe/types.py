"""Types and schemas for Executable Capability Probing."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class ExecutableProbeStatus(StrEnum):
    """Tri-state classification for CLI/executable health and compatibility."""

    CAPABLE = "capable"
    INCOMPATIBLE = "incompatible"
    BROKEN = "broken"


class ExecutableProbeResult(BaseModel):
    """Detailed diagnosis of an executable candidate probe."""

    model_config = ConfigDict(frozen=True)

    candidate_path: str = Field(
        ..., description="Absolute or PATH executable name probed"
    )
    status: ExecutableProbeStatus = Field(
        ..., description="Tri-state outcome: capable, incompatible, broken"
    )
    version: str | None = Field(
        default=None, description="Extracted version string if available"
    )
    detail: str = Field(
        default="",
        description="Detailed message, rejection reason, or error description",
    )
    launch_failed: bool = Field(
        default=False, description="True if OS could not spawn process (ENOENT/EACCES)"
    )
    is_capable: bool = Field(
        default=False, description="Convenience flag: True only when status == capable"
    )


class ProbeOptions(BaseModel):
    """Configuration options for executable probing."""

    model_config = ConfigDict(frozen=True)

    timeout_sec: float = Field(
        default=5.0, ge=0.5, le=60.0, description="Process execution timeout in seconds"
    )
    warm_up_retry: bool = Field(
        default=True,
        description="Whether to retry capability probe after version probe warms binary",
    )

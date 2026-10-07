"""Type contracts for CWD deferred workspace service binding and session resume order.

Defines schemas for outside-in assembly stages, session metadata headers,
bound workspace service descriptors, and order verification receipts.
Strictly adheres to 0 Any and typed dataclasses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class AssemblyStageKind(StrEnum):
    """Strict outside-in assembly stages for session initialization and resume."""

    ENTRY_PARSE = "entry_parse"
    SESSION_RESOLVED = "session_resolved"
    CWD_RESOLVED = "cwd_resolved"
    SERVICES_BOUND = "services_bound"
    RUNTIME_READY = "runtime_ready"


class AssemblyOrderViolationError(RuntimeError):
    """Raised when workspace services or runtime are instantiated out of strict outside-in order."""

    def __init__(self, message: str, current_stage: AssemblyStageKind, attempted_action: str) -> None:
        super().__init__(
            f"Assembly order violation: cannot perform '{attempted_action}' while in stage '{current_stage.value}'. {message}"
        )
        self.current_stage = current_stage
        self.attempted_action = attempted_action


@dataclass(frozen=True, slots=True)
class SessionMetadataHeader:
    """Header metadata for historical session selection and CWD calibration."""

    session_id: str
    original_cwd: str
    workspace_name: str = ""
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    total_turns: int = 0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceServiceDescriptor:
    """Descriptor for a workspace service strictly bound to the calibrated CWD."""

    service_name: str
    bound_cwd: str
    initialized_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    is_lazy: bool = False


@dataclass(frozen=True, slots=True)
class SessionResumeVerificationResult:
    """Comprehensive receipt verifying correct outside-in assembly and CWD binding."""

    valid: bool
    target_session_id: str
    resolved_cwd: str
    is_relocated: bool
    assembly_order_log: tuple[str, ...]
    bound_service_names: tuple[str, ...]
    error: str | None = None

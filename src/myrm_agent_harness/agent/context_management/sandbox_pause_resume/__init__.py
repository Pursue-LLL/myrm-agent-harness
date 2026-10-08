"""Sandbox session pause, in-place resume, and snapshot branching package.

[INPUT]
- agent.context_management.sandbox_pause_resume.sandbox_pause_resume_engine::SandboxPauseResumeEngine
  (POS: Core state machine engine coordinating pause, resume, snapshot creation, and restoration.)
- agent.context_management.sandbox_pause_resume.sandbox_pause_resume_suite::AgentkitPauseResumeSessionSandboxSuite
  (POS: High-level orchestration facade managing session lifecycle and snapshot auditing.)
- agent.context_management.sandbox_pause_resume.session_pause_types::compute_state_checksum,
  PauseResumeActionKind, PauseResumeReceipt, SandboxSessionRecord, SandboxSnapshotManifest,
  SessionLifecycleState (POS: Strongly typed domain contracts and audit receipts.)

[OUTPUT]
- Re-exports: AgentkitPauseResumeSessionSandboxSuite, SandboxPauseResumeEngine,
  compute_state_checksum, PauseResumeActionKind, PauseResumeReceipt, SandboxSessionRecord,
  SandboxSnapshotManifest, SessionLifecycleState

[POS]
Package entry point for sandbox pause, in-place resume, and snapshot restoration workflows.
"""

from __future__ import annotations

from .sandbox_pause_resume_engine import SandboxPauseResumeEngine
from .sandbox_pause_resume_suite import AgentkitPauseResumeSessionSandboxSuite
from .session_pause_types import (
    compute_state_checksum,
    PauseResumeActionKind,
    PauseResumeReceipt,
    SandboxSessionRecord,
    SandboxSnapshotManifest,
    SessionLifecycleState,
)

__all__ = [
    "AgentkitPauseResumeSessionSandboxSuite",
    "PauseResumeActionKind",
    "PauseResumeReceipt",
    "SandboxPauseResumeEngine",
    "SandboxSessionRecord",
    "SandboxSnapshotManifest",
    "SessionLifecycleState",
    "compute_state_checksum",
]

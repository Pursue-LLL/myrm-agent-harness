"""Immutable Host Sandbox and Zero Blast Radius Rollback Suite.

Mechanically enforces read-only OS paths and provides atomic zero-cost environment rollback.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.immutable_sandbox_rollback.immutable_policy import (
    DEFAULT_IMMUTABLE_SYSTEM_PATHS,
    ImmutableSandboxPolicyEngine,
)
from myrm_agent_harness.core.security.immutable_sandbox_rollback.rollback_manager import (
    SandboxAtomicRollbackManager,
)
from myrm_agent_harness.core.security.immutable_sandbox_rollback.types import (
    BlastRadiusTier,
    CommandBlastRadiusAssessment,
    RollbackResult,
    SandboxCheckpoint,
    SandboxMountSpec,
)

__all__ = [
    "DEFAULT_IMMUTABLE_SYSTEM_PATHS",
    "BlastRadiusTier",
    "CommandBlastRadiusAssessment",
    "ImmutableSandboxPolicyEngine",
    "RollbackResult",
    "SandboxAtomicRollbackManager",
    "SandboxCheckpoint",
    "SandboxMountSpec",
]

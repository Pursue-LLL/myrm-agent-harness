"""OS-level process sandbox for local/desktop execution.

Provides defense-in-depth below the software security layers (PathPolicy,
CommandRiskLevel, HITL) by restricting the shell process at the OS kernel
level.  In containerised (SaaS) environments the sandbox auto-detects that
isolation already exists and transparently degrades to NullProvider.

- sandbox_types.py: SandboxPolicy, SandboxMode, SandboxProvider protocol
- providers/: BwrapProvider (Linux), SeatbeltProvider (macOS), NullProvider
- detector.py: auto-select best available provider
"""

from myrm_agent_harness.toolkits.code_execution.sandbox.detector import (
    detect_sandbox_provider,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.mount_security_gate import (
    MountMode,
    MountSpec,
    MountValidationResult,
    MountViolationType,
    validate_and_sanitize_mounts,
    validate_mount_spec,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.privacy_ladder import (
    PrivacyLadderResult,
    PrivacyLadderScope,
    PrivacyLadderViolationType,
    PrivacyTier,
    validate_and_sanitize_persistence_paths,
    validate_privacy_ladder,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
    SandboxMode,
    SandboxPolicy,
    SandboxProvider,
    SandboxStatus,
)

__all__ = [
    "MountMode",
    "MountSpec",
    "MountValidationResult",
    "MountViolationType",
    "PrivacyLadderResult",
    "PrivacyLadderScope",
    "PrivacyLadderViolationType",
    "PrivacyTier",
    "SandboxMode",
    "SandboxPolicy",
    "SandboxProvider",
    "SandboxStatus",
    "detect_sandbox_provider",
    "validate_and_sanitize_mounts",
    "validate_and_sanitize_persistence_paths",
    "validate_mount_spec",
    "validate_privacy_ladder",
]

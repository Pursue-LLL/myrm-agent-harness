"""Zero-Trust Credential Isolation and Git Leakage Shield module.

[INPUT]
None.

[OUTPUT]
Exported public classes, functions, and exceptions.

[POS]
Harness core security subsystem preventing secret leaks in Git operations,
enforcing in-memory secret lifecycle, and redacting outbound logs.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.git_leak_shield.patterns import (
    SECRET_PATTERNS,
    mask_secret_value,
)
from myrm_agent_harness.core.security.git_leak_shield.probe import (
    PreCommitSecretProbe,
)
from myrm_agent_harness.core.security.git_leak_shield.redactor import (
    RedactedEgressFilter,
)
from myrm_agent_harness.core.security.git_leak_shield.types import (
    GitCommitSecretBlockedError,
    GitProbeResult,
    RedactionResult,
    SecretMatch,
)
from myrm_agent_harness.core.security.git_leak_shield.vault import (
    EphemeralSecretVault,
)

__all__ = [
    "EphemeralSecretVault",
    "GitCommitSecretBlockedError",
    "GitProbeResult",
    "PreCommitSecretProbe",
    "RedactedEgressFilter",
    "RedactionResult",
    "SECRET_PATTERNS",
    "SecretMatch",
    "mask_secret_value",
]

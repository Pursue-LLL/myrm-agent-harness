"""Directory trust gate and remote memory resolution suite.

[INPUT]
- Project directory paths, project memory configurations.

[OUTPUT]
- Gated memory endpoints and verified authorization decisions.

[POS]
- Harness core security module governing remote memory trust boundaries.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.directory_trust_gate.resolver import (
    RemoteMemoryTrustGate,
)
from myrm_agent_harness.core.security.directory_trust_gate.trust_store import (
    DirectoryTrustStore,
)
from myrm_agent_harness.core.security.directory_trust_gate.types import (
    ProjectMemoryConfig,
    ResolvedProjectRemote,
    TrustDecision,
)

__all__ = [
    "DirectoryTrustStore",
    "ProjectMemoryConfig",
    "RemoteMemoryTrustGate",
    "ResolvedProjectRemote",
    "TrustDecision",
]

"""Directory trust gate for remote memory access.

[INPUT]
- Directory paths, project memory configs, trust store queries.

[OUTPUT]
- Gated memory resolution, anti-TOCTOU validation, refusal notices.

[POS]
- Harness core security module separating local scope filtering from remote memory egress.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.directory_trust_remote_memory.resolver import (
    SinglePointRemoteMemoryResolver,
    build_remote_refusal_notice,
)
from myrm_agent_harness.core.security.directory_trust_remote_memory.trust_store import (
    DirectoryTrustStore,
)
from myrm_agent_harness.core.security.directory_trust_remote_memory.types import (
    ProjectMemoryConfig,
    RemoteMemoryConfig,
    ResolvedProjectRemote,
    TrustStatus,
)

__all__ = [
    "DirectoryTrustStore",
    "ProjectMemoryConfig",
    "RemoteMemoryConfig",
    "ResolvedProjectRemote",
    "SinglePointRemoteMemoryResolver",
    "TrustStatus",
    "build_remote_refusal_notice",
]

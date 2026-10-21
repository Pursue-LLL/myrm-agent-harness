"""Local-to-cloud task hot handoff and input consistency verification suite.

[OUTPUT]
- ExecutionEnvironment: Execution environment tier enum.
- HandoffPhase: Hot handoff lifecycle phase enum.
- MaterialDigest: Cryptographic input artifact digest.
- HandoffPayload: Portable task state container.
- HandoffReceipt: Audit verification receipt.
- MaterialIntegrityGuard: Chunked SHA-256 verifier.
- WorkspaceDeltaSyncer: Filesystem delta bundler.
- HotHandoffCoordinator: End-to-end evacuation, cloud relay, and reverse recall pipeline.

[INPUT]
- __future__

[OUTPUT]
- (模块级副作用与注册)

[POS]
Local-to-cloud task hot handoff and input consistency verification suite.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.hot_handoff.handoff_types import (
    ExecutionEnvironment,
    HandoffPayload,
    HandoffPhase,
    HandoffReceipt,
    MaterialDigest,
)
from myrm_agent_harness.runtime.hot_handoff.hot_handoff_coordinator import (
    HotHandoffCoordinator,
)
from myrm_agent_harness.runtime.hot_handoff.material_integrity_guard import (
    MaterialIntegrityGuard,
)
from myrm_agent_harness.runtime.hot_handoff.workspace_syncer import (
    WorkspaceDeltaSyncer,
)

__all__ = [
    "ExecutionEnvironment",
    "HandoffPayload",
    "HandoffPhase",
    "HandoffReceipt",
    "HotHandoffCoordinator",
    "MaterialDigest",
    "MaterialIntegrityGuard",
    "WorkspaceDeltaSyncer",
]

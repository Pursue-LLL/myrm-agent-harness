# [INPUT]: None (Public package facade)
# [OUTPUT]: MetaSessionOrchestrationAndChatCoworkDualTrackFusionSuite, HierarchicalMetaSessionOrchestrator, DualTrackMemoryBus, SubSessionFaultIsolator, orchestration_types
# [POS]: myrm_agent_harness.agent.context_management.meta_session_orchestration.__init__
"""Meta-Session Cascading Orchestration & Chat-Cowork Dual-Track Fusion (Item 332).

Provides unified hierarchical session dispatching, Chat & Cowork shared memory bus,
sub-session crash isolation, and realtime progress HUD streaming.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.meta_session_orchestration.dual_track_memory_bus import (
    DualTrackMemoryBus,
    format_dual_track_prompt_block,
)
from myrm_agent_harness.agent.context_management.meta_session_orchestration.hierarchical_meta_orchestrator import (
    HierarchicalMetaSessionOrchestrator,
    format_meta_progress_hud,
)
from myrm_agent_harness.agent.context_management.meta_session_orchestration.meta_session_fusion_suite import (
    MetaSessionOrchestrationAndChatCoworkDualTrackFusionSuite,
)
from myrm_agent_harness.agent.context_management.meta_session_orchestration.orchestration_types import (
    DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
    DEFAULT_SUBSESSION_TIMEOUT_SECONDS,
    DualTrackMemoryEnvelope,
    MetaSessionConfig,
    SessionHierarchyType,
    SessionTrackMode,
    SubSessionFailureReport,
    SubSessionHandoffDigest,
    SubSessionProgressCard,
    SubSessionStatus,
    SubSessionTaskDescriptor,
    compute_digest_hash,
    compute_envelope_hash,
)
from myrm_agent_harness.agent.context_management.meta_session_orchestration.sub_session_fault_isolator import (
    SubSessionFaultIsolator,
)

__all__ = [
    "DEFAULT_MAX_CONCURRENT_SUBSESSIONS",
    "DEFAULT_SUBSESSION_TIMEOUT_SECONDS",
    "DualTrackMemoryBus",
    "DualTrackMemoryEnvelope",
    "HierarchicalMetaSessionOrchestrator",
    "MetaSessionConfig",
    "MetaSessionOrchestrationAndChatCoworkDualTrackFusionSuite",
    "SessionHierarchyType",
    "SessionTrackMode",
    "SubSessionFailureReport",
    "SubSessionFaultIsolator",
    "SubSessionHandoffDigest",
    "SubSessionProgressCard",
    "SubSessionStatus",
    "SubSessionTaskDescriptor",
    "compute_digest_hash",
    "compute_envelope_hash",
    "format_dual_track_prompt_block",
    "format_meta_progress_hud",
]

# [INPUT]: None (Public package facade)
# [OUTPUT]: TieredTranscriptOffloadingAndSessionLifecycleResilienceSuite, TwoTierTranscriptOffloader, SingleFlightRefreshGate, DelayedSlotAllocator, DynamicCliCredentialEngine, resilience_types
# [POS]: myrm_agent_harness.agent.context_management.transcript_resilience.__init__
"""Transcript Offloading & Session Lifecycle Resilience Subsystem (Item 333).

Provides bounded heap transcript offloading, single-flight token refresh mutex gate,
delayed concurrency slot reservation contracts, and dynamic external CLI credential engine.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.transcript_resilience.delayed_slot_allocator import (
    DelayedSlotAllocator,
    format_active_slot_hud,
)
from myrm_agent_harness.agent.context_management.transcript_resilience.dynamic_cli_credential_engine import (
    DynamicCliCredentialEngine,
)
from myrm_agent_harness.agent.context_management.transcript_resilience.resilience_types import (
    DEFAULT_MAX_CONCURRENCY_SLOTS,
    DEFAULT_MAX_VIEWPORT_MESSAGES,
    DEFAULT_REFRESH_TIMEOUT_SECONDS,
    DelayedSessionSlot,
    DynamicCredentialSpec,
    HydratedTranscriptMessage,
    SingleFlightTokenState,
    TranscriptResilienceConfig,
    TranscriptStubRecord,
    compute_payload_hash,
)
from myrm_agent_harness.agent.context_management.transcript_resilience.single_flight_refresh_gate import (
    SingleFlightRefreshGate,
)
from myrm_agent_harness.agent.context_management.transcript_resilience.tiered_transcript_resilience_suite import (
    TieredTranscriptOffloadingAndSessionLifecycleResilienceSuite,
)
from myrm_agent_harness.agent.context_management.transcript_resilience.two_tier_transcript_offloader import (
    TwoTierTranscriptOffloader,
)

__all__ = [
    "DEFAULT_MAX_CONCURRENCY_SLOTS",
    "DEFAULT_MAX_VIEWPORT_MESSAGES",
    "DEFAULT_REFRESH_TIMEOUT_SECONDS",
    "DelayedSessionSlot",
    "DelayedSlotAllocator",
    "DynamicCliCredentialEngine",
    "DynamicCredentialSpec",
    "HydratedTranscriptMessage",
    "SingleFlightRefreshGate",
    "SingleFlightTokenState",
    "TieredTranscriptOffloadingAndSessionLifecycleResilienceSuite",
    "TranscriptResilienceConfig",
    "TranscriptStubRecord",
    "TwoTierTranscriptOffloader",
    "compute_payload_hash",
    "format_active_slot_hud",
]

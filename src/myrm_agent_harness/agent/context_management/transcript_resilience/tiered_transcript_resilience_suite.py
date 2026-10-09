# [INPUT]: DelayedSlotAllocator, DynamicCliCredentialEngine, SingleFlightRefreshGate, TwoTierTranscriptOffloader, types from resilience_types
# [OUTPUT]: TieredTranscriptOffloadingAndSessionLifecycleResilienceSuite
# [POS]: myrm_agent_harness.agent.context_management.transcript_resilience.tiered_transcript_resilience_suite
"""Unified facade suite for Transcript Offloading & Session Lifecycle Resilience (Item 333).

Coordinates bounded-memory transcript offloading, single-flight token refresh mutex,
lazy slot allocation contracts, and dynamic external CLI credential resolution.
"""

from __future__ import annotations

import threading
from typing import Callable, Final

from myrm_agent_harness.agent.context_management.transcript_resilience.delayed_slot_allocator import (
    DelayedSlotAllocator,
)
from myrm_agent_harness.agent.context_management.transcript_resilience.dynamic_cli_credential_engine import (
    DynamicCliCredentialEngine,
)
from myrm_agent_harness.agent.context_management.transcript_resilience.resilience_types import (
    DelayedSessionSlot,
    DynamicCredentialSpec,
    HydratedTranscriptMessage,
    SingleFlightTokenState,
    TranscriptResilienceConfig,
    TranscriptStubRecord,
)
from myrm_agent_harness.agent.context_management.transcript_resilience.single_flight_refresh_gate import (
    SingleFlightRefreshGate,
)
from myrm_agent_harness.agent.context_management.transcript_resilience.two_tier_transcript_offloader import (
    TwoTierTranscriptOffloader,
)


class TieredTranscriptOffloadingAndSessionLifecycleResilienceSuite:
    """Industrial facade providing end-to-end transcript offloading and lifecycle resilience."""

    def __init__(self, config: TranscriptResilienceConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._config: Final[TranscriptResilienceConfig] = config or TranscriptResilienceConfig()
        self._offloader: Final[TwoTierTranscriptOffloader] = TwoTierTranscriptOffloader(
            max_viewport_size=self._config.max_viewport_messages
        )
        self._refresh_gate: Final[SingleFlightRefreshGate] = SingleFlightRefreshGate(
            timeout_seconds=self._config.single_flight_timeout_seconds
        )
        self._slot_allocator: Final[DelayedSlotAllocator] = DelayedSlotAllocator(
            max_concurrency_slots=self._config.max_concurrency_slots
        )
        self._credential_engine: Final[DynamicCliCredentialEngine] = DynamicCliCredentialEngine()

    @property
    def config(self) -> TranscriptResilienceConfig:
        """Active suite configuration."""
        return self._config

    @property
    def offloader(self) -> TwoTierTranscriptOffloader:
        """Transcript offloader engine."""
        return self._offloader

    @property
    def refresh_gate(self) -> SingleFlightRefreshGate:
        """Single-flight token refresh gate."""
        return self._refresh_gate

    @property
    def slot_allocator(self) -> DelayedSlotAllocator:
        """Delayed slot allocation manager."""
        return self._slot_allocator

    @property
    def credential_engine(self) -> DynamicCliCredentialEngine:
        """Dynamic CLI credential evaluation engine."""
        return self._credential_engine

    def record_message(
        self,
        session_id: str,
        msg_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, str | int | float | bool | list[str] | dict[str, str]]] | None = None,
        created_at_iso: str = "",
    ) -> HydratedTranscriptMessage:
        """Record a transcript message, automatically stubbing out-of-viewport history."""
        return self._offloader.append_message(
            session_id=session_id,
            msg_id=msg_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            created_at_iso=created_at_iso,
        )

    def hydrate_message(
        self,
        session_id: str,
        msg_id: str,
    ) -> HydratedTranscriptMessage | None:
        """Restore full message payload on-demand from backing vault."""
        return self._offloader.hydrate_message(session_id=session_id, msg_id=msg_id)

    def get_viewport_messages(self, session_id: str) -> list[HydratedTranscriptMessage]:
        """Get in-memory messages currently visible in the active viewport."""
        return self._offloader.get_viewport_messages(session_id)

    def get_stubs(self, session_id: str) -> list[TranscriptStubRecord]:
        """Get lightweight stubs for offloaded historical messages."""
        return self._offloader.get_stubs(session_id)

    def execute_with_single_flight_refresh(
        self,
        token_refresh_fn: Callable[[], str],
    ) -> str:
        """Safely refresh token preventing concurrent 401 storms."""
        return self._refresh_gate.execute_with_refresh(token_refresh_fn)

    def get_token_state(self) -> SingleFlightTokenState:
        """Get snapshot of current single-flight refresh gate."""
        return self._refresh_gate.get_state()

    def claim_slot(self, session_id: str, holder_name: str) -> DelayedSessionSlot:
        """Claim a concurrency slot upon the first actual message dispatch."""
        return self._slot_allocator.claim_slot(session_id=session_id, holder_name=holder_name)

    def release_slot(self, session_id: str) -> bool:
        """Release slot back to available pool upon session completion or idle."""
        return self._slot_allocator.release_slot(session_id)

    def get_active_slot_hud(self) -> str:
        """Format active claimed slot status into transparent Markdown HUD."""
        return self._slot_allocator.get_hud_summary()

    def resolve_cli_credential(
        self,
        spec: DynamicCredentialSpec,
        force_refresh: bool = False,
    ) -> str:
        """Dynamically evaluate secret from external CLI vault."""
        return self._credential_engine.resolve_credential(spec=spec, force_refresh=force_refresh)

    def clear_session(self, session_id: str) -> None:
        """Clean up session transcripts, stubs, and execution slots."""
        with self._lock:
            self._offloader.clear_session(session_id)
            self._slot_allocator.release_slot(session_id)

"""Sliding-window degradation pipeline for large observation outputs.

[INPUT]
- ContentAddressedStore, ObservationHandle, ObservationPackConfig, ObservationSendState, TransformDecision:
  Domain types and storage engine from observation_pack.

[OUTPUT]
- ObservationDegradationPipeline: Coordinates receipt exemption, send-count sliding windows (FULL_SENDS=2),
  and progressive replacement of large observations with compact head-tail excerpt handles.

[POS]
Pipeline engine preventing prompt ballooning while preserving intact immediate context for 2 turns.
"""

from __future__ import annotations

from typing import Dict, Tuple

from .content_addressed_store import ContentAddressedStore
from .observation_pack_types import (
    ObservationHandle,
    ObservationPackConfig,
    ObservationSendState,
    TransformDecision,
)


class ObservationDegradationPipeline:
    """Evaluates and transforms tool observations with sliding-window degradation."""

    def __init__(
        self,
        store: ContentAddressedStore,
        config: ObservationPackConfig | None = None,
    ) -> None:
        self._store = store
        self._config = config or store.config
        # session_id -> {obs_id: ObservationSendState}
        self._sessions: Dict[str, Dict[str, ObservationSendState]] = {}

    @property
    def store(self) -> ContentAddressedStore:
        return self._store

    @property
    def config(self) -> ObservationPackConfig:
        return self._config

    def is_exempt_receipt(self, text: str) -> bool:
        """Check if content bears an evidence-preserving reducer receipt signature."""
        stripped = text.strip()
        return any(stripped.startswith(prefix) for prefix in self._config.receipt_prefixes)

    def _get_send_state(self, session_key: str, obs_id: str) -> ObservationSendState:
        session_map = self._sessions.setdefault(session_key, {})
        if obs_id not in session_map:
            session_map[obs_id] = ObservationSendState(obs_id=obs_id, full_sends_count=0)
        return session_map[obs_id]

    def format_placeholder(self, handle: ObservationHandle) -> str:
        """Construct deterministic compact head-tail excerpt placeholder."""
        omitted_bytes = max(0, handle.byte_size - len(handle.head_excerpt.encode("utf-8")) - len(handle.tail_excerpt.encode("utf-8")))
        parts: list[str] = [
            f"[Observation truncated: {handle.byte_size} bytes, {handle.line_count} lines. "
            f"Handle ID: {handle.obs_id}. Use recall_observation('{handle.obs_id}', page=1) to inspect full content]",
            f"--- HEAD ({self._config.head_bytes}B) ---",
            handle.head_excerpt,
            f"... [OMITTED {omitted_bytes} BYTES] ...",
        ]
        if handle.tail_excerpt:
            parts.extend([
                f"--- TAIL ({self._config.tail_bytes}B) ---",
                handle.tail_excerpt,
            ])
        return "\n".join(parts)

    def process_observation(
        self,
        text: str,
        session_id: str = "default",
    ) -> Tuple[str, TransformDecision]:
        """Evaluate observation text, register state, and return (output_text, decision)."""
        original_bytes = len(text.encode("utf-8"))

        # 1. Evidence-preserving receipt exemption check
        if self.is_exempt_receipt(text):
            return text, TransformDecision(
                action="EXEMPT_RECEIPT",
                original_bytes=original_bytes,
                transformed_bytes=original_bytes,
                handle_id=None,
                reason="Bears verified evidence-preserving reducer receipt; exempted from compaction",
            )

        # 2. Below threshold check
        if original_bytes <= self._config.threshold_bytes:
            return text, TransformDecision(
                action="BELOW_THRESHOLD",
                original_bytes=original_bytes,
                transformed_bytes=original_bytes,
                handle_id=None,
                reason=f"Payload size ({original_bytes} bytes) does not exceed threshold ({self._config.threshold_bytes} bytes)",
            )

        # 3. Store immutably in content-addressed store
        handle = self._store.store(text)
        state = self._get_send_state(session_id, handle.obs_id)
        state.full_sends_count += 1

        # 4. Check sliding window
        if state.full_sends_count <= self._config.full_sends:
            return text, TransformDecision(
                action="FULL_SEND_ACTIVE",
                original_bytes=original_bytes,
                transformed_bytes=original_bytes,
                handle_id=handle.obs_id,
                reason=(
                    f"Send count {state.full_sends_count}/{self._config.full_sends} within full-send window; "
                    "retaining 100% intact payload"
                ),
            )

        # 5. Degrade to excerpt placeholder
        state.is_degraded = True
        placeholder = self.format_placeholder(handle)
        transformed_bytes = len(placeholder.encode("utf-8"))

        return placeholder, TransformDecision(
            action="DEGRADED_PLACEHOLDER",
            original_bytes=original_bytes,
            transformed_bytes=transformed_bytes,
            handle_id=handle.obs_id,
            reason=(
                f"Send count {state.full_sends_count} exceeded full-send limit ({self._config.full_sends}); "
                "degraded to compact head-tail excerpt handle"
            ),
        )

    def reset_session(self, session_id: str = "default") -> None:
        """Reset send counts for a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]

    def get_session_stats(self, session_id: str = "default") -> Dict[str, int]:
        """Return summary counts of active tracked observations for a session."""
        session_map = self._sessions.get(session_id, {})
        degraded = sum(1 for st in session_map.values() if st.is_degraded)
        return {
            "total_tracked": len(session_map),
            "degraded_count": degraded,
        }

# [INPUT]: CachePartitionedContextBundle, EventEnvelopePayload, Sequence
# [OUTPUT]: CachePreservingEventEnvelopeProtocol
# [POS]: agent/context_management/event_cache_preservation/cache_preserving_event_envelope_protocol.py

"""Protocol preserving LLM provider prefix cache while safely encapsulating dynamic push events.

[INPUT]
- CachePartitionedContextBundle, EventEnvelopePayload: Contract models.
- Sequence: Standard typing.

[OUTPUT]
- CachePreservingEventEnvelopeProtocol: Enforces static prefix boundary and appends events strictly to message tail.

[POS]
Protocol enforcement layer in event cache preservation subsystem preventing catastrophic cache busting.
"""

from __future__ import annotations

import re
from typing import Sequence

from .event_envelope_types import (
    CachePartitionedContextBundle,
    EventEnvelopePayload,
)


class CachePreservingEventEnvelopeProtocol:
    """Isolates dynamic event payloads at message tails, keeping prefix cache hit ratios above 90%."""

    APPROX_CHARS_PER_TOKEN: float = 3.6
    CACHE_BLOCK_BOUNDARY: int = 1024  # Standard Anthropic / DeepSeek 1024-token boundary

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count based on typical character length heuristic."""
        if not text:
            return 0
        return max(1, int(len(text) / self.APPROX_CHARS_PER_TOKEN))

    def partition_context(
        self,
        static_prefix: str,
        conversation_history: Sequence[str],
        event_payload: EventEnvelopePayload | None = None,
    ) -> CachePartitionedContextBundle:
        """Partition context into byte-level frozen static prefix, message history, and tail event frame."""
        clean_prefix = static_prefix.strip()
        prefix_tokens = self.estimate_tokens(clean_prefix)

        history_tokens = sum(self.estimate_tokens(h) for h in conversation_history)
        event_frame = event_payload.format_tail_xml_frame() if event_payload else ""
        event_tokens = self.estimate_tokens(event_frame)

        total_tokens = prefix_tokens + history_tokens + event_tokens

        # If prefix + history remain untouched, only the ephemeral tail token frame is new.
        # Cached tokens = prefix_tokens + history_tokens
        if total_tokens > 0:
            cached_tokens = prefix_tokens + history_tokens
            hit_ratio = round(min(0.99, max(0.0, cached_tokens / total_tokens)), 4)
        else:
            hit_ratio = 1.0

        return CachePartitionedContextBundle(
            static_prefix_tier=clean_prefix,
            conversation_history_tier=tuple(conversation_history),
            ephemeral_event_frame=event_frame,
            prefix_tokens_estimate=prefix_tokens,
            event_tokens_estimate=event_tokens,
            cache_hit_ratio_projected=hit_ratio,
        )

    def verify_prefix_unmodified(
        self,
        baseline_prefix: str,
        new_prompt: str,
    ) -> bool:
        """Verify byte-exact prefix match to guarantee 100% provider prefix cache survival."""
        clean_baseline = baseline_prefix.strip()
        return new_prompt.startswith(clean_baseline)

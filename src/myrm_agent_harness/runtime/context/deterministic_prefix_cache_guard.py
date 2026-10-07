"""Deterministic hash-pinned prefix cache guard.

Monitors SHA-256 stability of frozen system prompts and append-only history streams,
preventing devastating KV-cache invalidation across multi-turn agent sessions.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.deterministic_prefix_cache_types import (
    PrefixCacheHitReport,
    PrefixHashFingerprint,
)


class PrefixCacheBreachError(ValueError):
    """Raised when an immutable prefix or frozen system prompt was mutated in place."""


class DeterministicPrefixCacheGuard:
    """Cryptographic watchdog ensuring prefix immutability and tracking KV-cache hit ratios."""

    def __init__(self, min_acceptable_hit_ratio: float = 0.95) -> None:
        self._min_acceptable_hit_ratio = min_acceptable_hit_ratio
        self._latest_fingerprints: dict[str, PrefixHashFingerprint] = {}
        self._history_snapshots: dict[str, list[str]] = {}
        self._telemetry_history: dict[str, list[PrefixCacheHitReport]] = {}

    @staticmethod
    def compute_sha256(text: str) -> str:
        """Compute standard hex-encoded SHA-256 digest of utf-8 text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def verify_and_anchor_prefix(
        self,
        session_id: str,
        turn_index: int,
        static_system_prompt: str,
        immutable_history_turns: Sequence[str],
        metadata: dict[str, str] | None = None,
    ) -> PrefixHashFingerprint:
        """Validate append-only invariants, compute cryptographic hashes, and anchor prefix."""
        now = time.time()
        static_sha = self.compute_sha256(static_system_prompt)

        prev_fingerprint = self._latest_fingerprints.get(session_id)
        prev_history = self._history_snapshots.get(session_id)

        # 1. Assert frozen system prompt hasn't mutated across turns
        if prev_fingerprint is not None and prev_fingerprint.static_system_sha256 != static_sha:
            raise PrefixCacheBreachError(
                f"Frozen system prompt mutated at turn {turn_index}: "
                f"expected {prev_fingerprint.static_system_sha256[:12]}..., got {static_sha[:12]}..."
            )

        # 2. Assert history stream is strictly append-only (no historical mutation)
        if prev_history is not None:
            if len(immutable_history_turns) < len(prev_history):
                raise PrefixCacheBreachError(
                    f"History truncated at turn {turn_index}: {len(immutable_history_turns)} < {len(prev_history)}"
                )
            for idx, old_turn in enumerate(prev_history):
                if immutable_history_turns[idx] != old_turn:
                    raise PrefixCacheBreachError(
                        f"Historical turn at index {idx} mutated: "
                        f"prefix cache invalidated at turn {turn_index}"
                    )

        history_joined = "\n".join(immutable_history_turns)
        history_sha = self.compute_sha256(history_joined)
        combined_sha = self.compute_sha256(f"{static_sha}::{history_sha}")

        fingerprint = PrefixHashFingerprint(
            session_id=session_id,
            turn_index=turn_index,
            static_system_sha256=static_sha,
            immutable_history_sha256=history_sha,
            combined_prefix_sha256=combined_sha,
            prefix_length_chars=len(static_system_prompt) + len(history_joined),
            timestamp=now,
            metadata=dict(metadata or {}),
        )

        self._latest_fingerprints[session_id] = fingerprint
        self._history_snapshots[session_id] = list(immutable_history_turns)
        return fingerprint

    def record_cache_hit_telemetry(
        self,
        session_id: str,
        turn_index: int,
        reported_cache_hit_tokens: int,
        reported_total_prompt_tokens: int,
    ) -> PrefixCacheHitReport:
        """Analyze model inference token usage and generate cache hit report."""
        now = time.time()
        if reported_total_prompt_tokens > 0:
            ratio = float(reported_cache_hit_tokens / reported_total_prompt_tokens)
        else:
            ratio = 1.0

        breach = ratio < self._min_acceptable_hit_ratio
        reason = (
            f"Cache hit ratio {ratio:.3f} fell below minimum target {self._min_acceptable_hit_ratio:.3f}"
            if breach
            else None
        )

        report = PrefixCacheHitReport(
            session_id=session_id,
            turn_index=turn_index,
            is_prefix_stable=not breach,
            reported_cache_hit_tokens=reported_cache_hit_tokens,
            reported_total_prompt_tokens=reported_total_prompt_tokens,
            cache_hit_ratio=ratio,
            breach_detected=breach,
            breach_reason=reason,
            timestamp=now,
        )

        self._telemetry_history.setdefault(session_id, []).append(report)
        return report

    def get_latest_fingerprint(
        self, session_id: str
    ) -> PrefixHashFingerprint | None:
        """Return the current anchored prefix fingerprint for the session."""
        return self._latest_fingerprints.get(session_id)

    def get_telemetry_history(
        self, session_id: str
    ) -> tuple[PrefixCacheHitReport, ...]:
        """Return all recorded cache hit reports for the session."""
        return tuple(self._telemetry_history.get(session_id, []))

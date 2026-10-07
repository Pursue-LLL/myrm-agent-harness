"""Append-only context pipeline and deterministic summarization engine.

Enforces three-zone context partitioning (static system frozen, immutable append-only
history stream, active working tail) and produces seed-pinned idempotent summaries.

[INPUT]
- runtime.context.deterministic_prefix_cache_guard::DeterministicPrefixCacheGuard (POS: Deterministic
  hash-pinned prefix cache guard.)
- runtime.context.deterministic_prefix_cache_types::DeterministicSummaryBlock, PrefixHashFingerprint (POS:
  Types and data models for deterministic hash-pinned prefix cache guard and append-only pipeline.)

[OUTPUT]
- AppendOnlyContextPipeline: Manages append-only prompt sequences and deterministic summarization.

[POS]
Append-only context pipeline and deterministic summarization engine.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.deterministic_prefix_cache_guard import (
    DeterministicPrefixCacheGuard,
)
from myrm_agent_harness.runtime.context.deterministic_prefix_cache_types import (
    DeterministicSummaryBlock,
    PrefixHashFingerprint,
)


class AppendOnlyContextPipeline:
    """Manages append-only prompt sequences and deterministic summarization."""

    def __init__(self) -> None:
        self._static_systems: dict[str, str] = {}
        self._immutable_histories: dict[str, list[str]] = {}
        self._active_tails: dict[str, str] = {}

    def set_static_system(self, session_id: str, system_prompt: str) -> None:
        """Set or update the frozen static system prompt for a session."""
        self._static_systems[session_id] = system_prompt.strip()

    def get_static_system(self, session_id: str) -> str:
        """Return the frozen system prompt for the session."""
        return self._static_systems.get(session_id, "")

    def append_history_turn(self, session_id: str, turn_text: str) -> int:
        """Append an immutable conversational turn to the historical stream."""
        history = self._immutable_histories.setdefault(session_id, [])
        history.append(turn_text.strip())
        return len(history)

    def get_history_turns(self, session_id: str) -> tuple[str, ...]:
        """Return an immutable tuple of all historical turns."""
        return tuple(self._immutable_histories.get(session_id, []))

    def set_active_tail(self, session_id: str, tail_text: str) -> None:
        """Set the active working tail for the current turn."""
        self._active_tails[session_id] = tail_text.strip()

    def get_active_tail(self, session_id: str) -> str:
        """Return the active working tail for the session."""
        return self._active_tails.get(session_id, "")

    def create_deterministic_compaction(
        self,
        session_id: str,
        start_turn: int,
        end_turn: int,
        key_facts: Sequence[str],
        seed: int = 42,
    ) -> DeterministicSummaryBlock:
        """Generate a cryptographically deterministic summary block with pinned seed.

        Sorts key facts deterministically and produces an identical sha256 across all runs.
        """
        sorted_facts = sorted(f.strip() for f in key_facts if f.strip())
        lines = [
            f"[DETERMINISTIC_SUMMARY:SEED={seed}:TURNS={start_turn}-{end_turn}]",
            "Key contextual anchors:",
        ]
        for fact in sorted_facts:
            lines.append(f"- {fact}")

        content = "\n".join(lines)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        summary_id = f"dsum_{content_hash[:10]}"

        return DeterministicSummaryBlock(
            summary_id=summary_id,
            deterministic_seed=seed,
            source_turns_range=(start_turn, end_turn),
            content=content,
            sha256_hash=content_hash,
            created_at=time.time(),
        )

    def assemble_full_context_stream(
        self,
        session_id: str,
        guard: DeterministicPrefixCacheGuard | None = None,
        turn_index: int = 1,
    ) -> tuple[str, PrefixHashFingerprint | None]:
        """Assemble complete context stream and optionally anchor cryptographic prefix fingerprint."""
        static_sys = self.get_static_system(session_id)
        history = self.get_history_turns(session_id)
        tail = self.get_active_tail(session_id)

        parts: list[str] = []
        if static_sys:
            parts.append(static_sys)
        if history:
            parts.append("\n".join(history))
        if tail:
            parts.append(tail)

        full_stream = "\n\n".join(parts)

        fingerprint: PrefixHashFingerprint | None = None
        if guard is not None:
            fingerprint = guard.verify_and_anchor_prefix(
                session_id=session_id,
                turn_index=turn_index,
                static_system_prompt=static_sys,
                immutable_history_turns=history,
            )

        return full_stream, fingerprint

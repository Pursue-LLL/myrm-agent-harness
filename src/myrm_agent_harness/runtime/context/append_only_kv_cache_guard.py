"""Append-only context tail invariant and KV cache protection engine.

Implements the Pi Harness v2 KV cache stability specification:
1. Append-Only Context Tail Invariant:
   Provider context must only grow at the tail. Inserting before the previous
   request's tail invalidates the provider's KV cache (Prompt Cache) and multiplies
   token costs.
2. Mid-Turn Deferred Writes:
   External configuration updates, environment observations, and custom entries
   arriving during an active turn are deferred to the next checkpoint boundary,
   ensuring they are safely appended at the tail.
3. Compaction Exemption Token:
   Context compaction is the sole deliberate exception permitted to reconstruct
   the prefix baseline.

[INPUT]
- langchain_core.messages.BaseMessage
- Sequence[BaseMessage]
- CompactionBypassToken

[OUTPUT]
- KVCacheTailInvariantViolationError
- ViolationType
- CompactionBypassToken
- DeferredWriteType
- DeferredWriteItem
- DeferredWriteBuffer
- AppendOnlyContextTailInvariantGuard

[POS]
Harness runtime context layer. Enforces strict append-only context growth,
preserves LLM KV cache prefix hit rates, and buffers mid-turn side mutations.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)


class ViolationType(StrEnum):
    """Specific cause for an append-only invariant violation."""

    PREFIX_TRUNCATED = "prefix_truncated"
    PREFIX_MUTATED = "prefix_mutated"
    MID_STREAM_INSERTION = "mid_stream_insertion"
    REORDERED = "reordered"


class KVCacheTailInvariantViolationError(Exception):
    """Raised when context pipeline attempts to mutate messages before the tail."""

    def __init__(self, violation_type: ViolationType, message: str, index: int) -> None:
        super().__init__(f"[{violation_type.value}] at index {index}: {message}")
        self.violation_type = violation_type
        self.index = index


@dataclass(slots=True, frozen=True)
class CompactionBypassToken:
    """Deliberate exemption token permitting prefix reconstruction for compaction."""

    token_id: str
    session_id: str
    reason: str
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    @classmethod
    def create(cls, session_id: str, reason: str = "compaction") -> CompactionBypassToken:
        """Issue a fresh compaction bypass token."""
        return cls(
            token_id=f"cbt-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            reason=reason,
        )


class DeferredWriteType(StrEnum):
    """Category of mid-turn deferred mutations."""

    CONFIG_UPDATE = "config_update"
    ENVIRONMENT_FACT = "environment_fact"
    CUSTOM_ENTRY = "custom_entry"
    SIDE_CHANNEL_NOTE = "side_channel_note"


@dataclass(slots=True, frozen=True)
class DeferredWriteItem:
    """Mid-turn mutation deferred to the next checkpoint."""

    write_id: str
    write_type: DeferredWriteType
    payload: str
    run_id: str | None = None
    created_at_ms: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


class DeferredWriteBuffer:
    """Thread-safe staging buffer for mid-turn writes deferred to checkpoints."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[DeferredWriteItem] = []

    def stage_write(
        self,
        write_type: DeferredWriteType,
        payload: str,
        *,
        run_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> DeferredWriteItem:
        """Stage a mutation while a turn is active."""
        item = DeferredWriteItem(
            write_id=f"dw-{uuid.uuid4().hex[:12]}",
            write_type=write_type,
            payload=payload,
            run_id=run_id,
            created_at_ms=int(time.time() * 1000),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._items.append(item)
        return item

    def flush_at_checkpoint(
        self,
        messages: Sequence[BaseMessage],
    ) -> list[BaseMessage]:
        """Atomically append all staged writes to the tail of messages."""
        with self._lock:
            if not self._items:
                return list(messages)

            flushed = list(self._items)
            self._items.clear()

        # Render deferred writes as tail notice messages preserving prefix cache
        result = list(messages)
        for it in flushed:
            rendered = f"[{it.write_type.value.upper()}] {it.payload}"
            result.append(HumanMessage(content=rendered))

        return result

    @property
    def pending_count(self) -> int:
        """Count of pending staged items."""
        with self._lock:
            return len(self._items)


class AppendOnlyContextTailInvariantGuard:
    """Guards context messages against non-tail mutations to protect LLM KV cache."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._lock = threading.Lock()
        self._last_sent_signatures: list[str] = []

    @staticmethod
    def compute_message_signature(message: BaseMessage) -> str:
        """Compute deterministic cryptographic signature for a message."""
        role = getattr(message, "role", None) or type(message).__name__
        content_repr = str(message.content or "")
        tool_calls_repr = ""
        if isinstance(message, AIMessage) and bool(getattr(message, "tool_calls", None)):
            tc = getattr(message, "tool_calls", [])
            tool_calls_repr = json.dumps(tc, sort_keys=True, ensure_ascii=True)
        elif isinstance(message, ToolMessage):
            tool_calls_repr = str(getattr(message, "tool_call_id", ""))

        raw = f"{role}:{content_repr}:{tool_calls_repr}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def record_provider_request(self, messages: Sequence[BaseMessage]) -> None:
        """Record context signatures successfully dispatched to provider."""
        with self._lock:
            self._last_sent_signatures = [
                self.compute_message_signature(msg) for msg in messages
            ]

    def verify_append_only(
        self,
        candidate_messages: Sequence[BaseMessage],
        *,
        bypass_token: CompactionBypassToken | None = None,
    ) -> bool:
        """Enforce append-only tail invariant against candidate messages.

        Returns True if candidate satisfies the invariant or holds a valid bypass token.
        Raises KVCacheTailInvariantViolationError on any violation.
        """
        with self._lock:
            candidate_sigs = [
                self.compute_message_signature(msg) for msg in candidate_messages
            ]

            # 1. Compaction deliberate exemption
            if bypass_token is not None:
                if bypass_token.session_id == self.session_id:
                    self._last_sent_signatures = candidate_sigs
                    return True
                raise KVCacheTailInvariantViolationError(
                    ViolationType.PREFIX_MUTATED,
                    f"Compaction bypass token session mismatch ({bypass_token.session_id} != {self.session_id})",
                    0,
                )

            # 2. First request: no prior baseline
            if not self._last_sent_signatures:
                self._last_sent_signatures = candidate_sigs
                return True

            prev_len = len(self._last_sent_signatures)
            cand_len = len(candidate_sigs)

            # 3. Check for truncation before previous tail
            if cand_len < prev_len:
                raise KVCacheTailInvariantViolationError(
                    ViolationType.PREFIX_TRUNCATED,
                    f"Candidate length ({cand_len}) is shorter than previous request tail ({prev_len})",
                    cand_len,
                )

            # 4. Check prefix identity: candidate must exactly match previous signatures
            for idx in range(prev_len):
                prev_sig = self._last_sent_signatures[idx]
                cand_sig = candidate_sigs[idx]
                if prev_sig != cand_sig:
                    # Check whether it's an insertion causing shift or direct mutation
                    if idx + 1 < cand_len and candidate_sigs[idx + 1] == prev_sig:
                        raise KVCacheTailInvariantViolationError(
                            ViolationType.MID_STREAM_INSERTION,
                            f"Mid-stream insertion detected at index {idx}; shifts existing prefix and invalidates KV cache",
                            idx,
                        )
                    raise KVCacheTailInvariantViolationError(
                        ViolationType.PREFIX_MUTATED,
                        f"Message at index {idx} was mutated; breaks previous prefix and invalidates KV cache",
                        idx,
                    )

            # 5. Invariant satisfied: candidate only grows at tail
            self._last_sent_signatures = candidate_sigs
            return True

    @property
    def baseline_prefix_length(self) -> int:
        """Number of messages currently anchored in the prefix cache baseline."""
        with self._lock:
            return len(self._last_sent_signatures)

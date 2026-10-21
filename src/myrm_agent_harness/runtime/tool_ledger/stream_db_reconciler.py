"""Stream tail and persistent DB reconciler with lossy reasoning deduplication.

Faithfully implements Hermes Desktop reconcileStreamedWithDb and dropLossyStreamedReasoning:
- Aligns in-flight streamed messages with authoritative DB history without UI DOM flushes.
- Preserves client-optimistic user messages awaiting database commit.
- Stitches partial stream tails to finalized DB records.
- Drops lossy / chunk-truncated streamed reasoning bubbles to prevent duplicate UI rendering.

[OUTPUT]
- StreamedMessage: Transient UI streaming message representation.
- DbMessage: Authoritative persistent message record loaded from database.
- ReconciledMessage: Merged, DOM-stable message ready for UI rendering.
- StreamDbReconciler: High-performance reconciliation engine.

[INPUT]
- __future__
- time
- dataclasses

[OUTPUT]
- StreamedMessage
- DbMessage
- ReconciledMessage
- StreamDbReconciler

[POS]
Stream tail and persistent DB reconciler with lossy reasoning deduplication.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StreamedMessage:
    """Transient message state accumulated in client-side memory during active streaming."""

    id: str
    role: str
    content: str
    reasoning: str = ""
    tool_calls: tuple[str, ...] = field(default_factory=tuple)
    is_optimistic: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class DbMessage:
    """Authoritative persistent message record retrieved from database or storage."""

    id: str
    role: str
    content: str
    reasoning: str = ""
    tool_calls: tuple[str, ...] = field(default_factory=tuple)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ReconciledMessage:
    """Authoritative, DOM-safe merged message for frontend display."""

    id: str
    role: str
    content: str
    reasoning: str = ""
    tool_calls: tuple[str, ...] = field(default_factory=tuple)
    is_optimistic: bool = False
    was_stitched: bool = False
    reasoning_lossy_dropped: bool = False
    timestamp: float = field(default_factory=time.time)


class StreamDbReconciler:
    """Reconciles transient client-side stream tails against persistent database records."""

    @staticmethod
    def drop_lossy_streamed_reasoning(
        streamed_reasoning: str, db_reasoning: str
    ) -> tuple[str, bool]:
        """Eliminate redundant lossy reasoning chunks when DB holds authoritative reasoning.

        When network interrupts mid-stream, transient memory may contain an incomplete prefix
        or corrupted chunk copy of the model's reasoning. If the database record contains a
        matching prefix or complete thought process, we drop the lossy transient bubble
        to avoid duplicated visual stacks in the chat view.
        """
        trimmed_stream = streamed_reasoning.strip()
        trimmed_db = db_reasoning.strip()

        if not trimmed_stream:
            return trimmed_db, False

        if not trimmed_db:
            return trimmed_stream, False

        # If stream is identical to DB or a partial prefix of DB record, use DB and drop lossy stream
        if trimmed_db.startswith(trimmed_stream) or trimmed_stream == trimmed_db:
            return trimmed_db, True

        # If DB is a prefix of streamed (stream has progressed further than DB commit)
        if trimmed_stream.startswith(trimmed_db):
            return trimmed_stream, False

        # In case of non-overlapping divergence, prioritize finalized DB record to guarantee truth
        return trimmed_db, True

    @classmethod
    def reconcile(
        cls,
        streamed_messages: list[StreamedMessage] | tuple[StreamedMessage, ...],
        db_messages: list[DbMessage] | tuple[DbMessage, ...],
    ) -> list[ReconciledMessage]:
        """Stitch transient stream messages with database truth while preserving optimistic inputs.

        Algorithm:
        1. Index authoritative DB messages by ID and role.
        2. Identify and preserve uncommitted optimistic user messages from the stream.
        3. Match the trailing assistant message to stitch partial streaming buffers with DB truth.
        4. Retain original stream element IDs where applicable to prevent visual DOM tearing.
        """
        reconciled: list[ReconciledMessage] = []
        db_by_id: dict[str, DbMessage] = {m.id: m for m in db_messages}

        # Step 1: Append all committed DB messages
        for db_msg in db_messages:
            reconciled.append(
                ReconciledMessage(
                    id=db_msg.id,
                    role=db_msg.role,
                    content=db_msg.content,
                    reasoning=db_msg.reasoning,
                    tool_calls=db_msg.tool_calls,
                    is_optimistic=False,
                    was_stitched=False,
                    reasoning_lossy_dropped=False,
                    timestamp=db_msg.timestamp,
                )
            )

        # Step 2: Handle transient streamed messages
        for s_msg in streamed_messages:
            # Case A: Preserving uncommitted optimistic user messages
            if s_msg.is_optimistic and s_msg.id not in db_by_id:
                reconciled.append(
                    ReconciledMessage(
                        id=s_msg.id,
                        role=s_msg.role,
                        content=s_msg.content,
                        reasoning=s_msg.reasoning,
                        tool_calls=s_msg.tool_calls,
                        is_optimistic=True,
                        was_stitched=False,
                        reasoning_lossy_dropped=False,
                        timestamp=s_msg.timestamp,
                    )
                )
                continue

            # Case B: Streamed message matches an existing DB message (stitch tail)
            if s_msg.id in db_by_id:
                matched_idx = next(
                    (i for i, r in enumerate(reconciled) if r.id == s_msg.id),
                    None,
                )
                if matched_idx is not None:
                    existing_db = reconciled[matched_idx]
                    final_reasoning, dropped = cls.drop_lossy_streamed_reasoning(
                        s_msg.reasoning, existing_db.reasoning
                    )
                    # Use longest / authoritative content
                    final_content = (
                        existing_db.content
                        if len(existing_db.content) >= len(s_msg.content)
                        else s_msg.content
                    )
                    merged_tools = (
                        existing_db.tool_calls
                        if existing_db.tool_calls
                        else s_msg.tool_calls
                    )

                    reconciled[matched_idx] = ReconciledMessage(
                        id=s_msg.id,
                        role=existing_db.role,
                        content=final_content,
                        reasoning=final_reasoning,
                        tool_calls=merged_tools,
                        is_optimistic=False,
                        was_stitched=True,
                        reasoning_lossy_dropped=dropped,
                        timestamp=existing_db.timestamp,
                    )

        return reconciled

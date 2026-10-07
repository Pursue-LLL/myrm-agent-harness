# ============================================================================
# Transcript Append-Only Invariant Enforcer Engine (Item 169)
# Strict verification of historical message immutability, zero in-place mutation,
# and non-destructive incremental delta evolution for optimal KV-cache retention.
# ============================================================================

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from langchain_core.messages import BaseMessage, HumanMessage

from .transcript_enforcer_types import (
    AppendOnlyEnforcementResult,
    DeltaCorrectionNote,
    MessageFingerprint,
    TurnTranscriptSnapshot,
    ViolationKind,
    ViolationRecord,
)

logger = logging.getLogger(__name__)


def _compute_sha256(text: str) -> str:
    """Compute deterministic SHA-256 hex digest for text string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint_message(index: int, msg: BaseMessage) -> MessageFingerprint:
    """Compute cryptographic hash fingerprint for a single message."""
    content_str = str(msg.content)
    return MessageFingerprint(
        index=index,
        role=str(msg.type),
        content_sha256=_compute_sha256(content_str),
        content_length=len(content_str),
    )


class TranscriptAppendOnlyInvariantEnforcer:
    """Hard gate enforcing append-only invariant on conversation message transcripts."""

    def commit_turn_snapshot(
        self,
        turn_index: int,
        messages: Sequence[BaseMessage],
    ) -> TurnTranscriptSnapshot:
        """Capture immutable cryptographic checkpoint of committed message sequence."""
        fingerprints = tuple(
            _fingerprint_message(idx, msg) for idx, msg in enumerate(messages)
        )
        agg_raw = "|".join(f"{fp.role}:{fp.content_sha256}" for fp in fingerprints)
        agg_hash = _compute_sha256(agg_raw)

        logger.info(
            "Committed turn snapshot #%d: %d messages, prefix_hash=%s",
            turn_index,
            len(messages),
            agg_hash[:10],
        )

        return TurnTranscriptSnapshot(
            turn_index=turn_index,
            message_count=len(messages),
            aggregate_prefix_sha256=agg_hash,
            fingerprints=fingerprints,
        )

    def validate_append_only(
        self,
        messages: Sequence[BaseMessage],
        last_snapshot: TurnTranscriptSnapshot | None = None,
    ) -> AppendOnlyEnforcementResult:
        """Verify that incoming message sequence strictly preserves historical prefix."""
        if last_snapshot is None or last_snapshot.message_count == 0:
            return AppendOnlyEnforcementResult(
                is_valid_append_only=True,
                appended_message_count=len(messages),
                violations=(),
                diagnostic_message="Initial turn: append-only invariant trivially satisfied.",
            )

        violations: list[ViolationRecord] = []
        expected_count = last_snapshot.message_count
        actual_count = len(messages)

        # Check for message deletion (truncation of entire message nodes)
        if actual_count < expected_count:
            violations.append(
                ViolationRecord(
                    violation_kind=ViolationKind.MESSAGE_DELETED,
                    message_index=actual_count,
                    expected_fingerprint=last_snapshot.fingerprints[actual_count],
                    actual_content_preview="<EOF>",
                    detail=(
                        f"History length reduced from {expected_count} to {actual_count} messages. "
                        f"{expected_count - actual_count} messages deleted from history."
                    ),
                )
            )
            return AppendOnlyEnforcementResult(
                is_valid_append_only=False,
                appended_message_count=0,
                violations=tuple(violations),
                diagnostic_message=(
                    "CRITICAL CACHE BREACH: Historical messages deleted from conversation transcript!"
                ),
            )

        # Verify historical prefix messages byte-for-byte
        for idx in range(expected_count):
            exp_fp = last_snapshot.fingerprints[idx]
            actual_msg = messages[idx]
            actual_fp = _fingerprint_message(idx, actual_msg)
            actual_content = str(actual_msg.content)

            # Role change check
            if actual_fp.role != exp_fp.role:
                violations.append(
                    ViolationRecord(
                        violation_kind=ViolationKind.ROLE_CHANGED,
                        message_index=idx,
                        expected_fingerprint=exp_fp,
                        actual_content_preview=actual_content[:60],
                        detail=f"Message #{idx} role changed from '{exp_fp.role}' to '{actual_fp.role}'.",
                    )
                )
                continue

            # Content mutation / in-place truncation check
            if actual_fp.content_sha256 != exp_fp.content_sha256:
                if actual_fp.content_length < exp_fp.content_length:
                    kind = ViolationKind.MESSAGE_TRUNCATED
                    detail = (
                        f"Message #{idx} truncated in-place ({exp_fp.content_length} -> {actual_fp.content_length} chars). "
                        "In-place truncation destroys prefix KV-cache!"
                    )
                else:
                    kind = ViolationKind.CONTENT_MUTATED
                    detail = (
                        f"Message #{idx} mutated in-place. Literal text altered from historical turn snapshot."
                    )

                violations.append(
                    ViolationRecord(
                        violation_kind=kind,
                        message_index=idx,
                        expected_fingerprint=exp_fp,
                        actual_content_preview=actual_content[:60],
                        detail=detail,
                    )
                )

        is_valid = len(violations) == 0
        appended_count = actual_count - expected_count

        if is_valid:
            diag = (
                f"Append-only invariant strictly satisfied. {expected_count} historical messages "
                f"100% byte-identical. {appended_count} new messages appended to tail."
            )
        else:
            diag = (
                f"CRITICAL CACHE BREACH: {len(violations)} historical violations detected! "
                "Any in-place mutation breaks prefix cache and causes 100% prefill recomputation."
            )

        return AppendOnlyEnforcementResult(
            is_valid_append_only=is_valid,
            appended_message_count=appended_count,
            violations=tuple(violations),
            diagnostic_message=diag,
        )

    def create_delta_correction_message(
        self,
        target_message_index: int,
        correction_summary: str,
    ) -> HumanMessage:
        """Create structured delta evolution note appended to tail without mutating history."""
        rendered = (
            f'<context_delta_evolution target_index="{target_message_index}">\n'
            f"  <summary>{correction_summary.strip()}</summary>\n"
            "</context_delta_evolution>"
        )
        return HumanMessage(content=rendered)

    def safeguard_or_repair_messages(
        self,
        incoming_messages: Sequence[BaseMessage],
        last_snapshot: TurnTranscriptSnapshot,
        committed_baseline_messages: Sequence[BaseMessage],
    ) -> tuple[tuple[BaseMessage, ...], AppendOnlyEnforcementResult]:
        """Verify messages, and if in-place mutation occurred, repair prefix from committed baseline."""
        validation = self.validate_append_only(incoming_messages, last_snapshot)
        if validation.is_valid_append_only:
            return tuple(incoming_messages), validation

        logger.warning(
            "Repairing transcript to preserve KV-cache! %d violations detected",
            len(validation.violations),
        )

        repaired: list[BaseMessage] = list(committed_baseline_messages[: last_snapshot.message_count])

        # Convert attempted mutations into tail delta notes
        delta_notes: list[str] = []
        for v in validation.violations:
            if v.violation_kind in (ViolationKind.CONTENT_MUTATED, ViolationKind.MESSAGE_TRUNCATED):
                delta_notes.append(
                    f"Message #{v.message_index} modified content note: {v.actual_content_preview}"
                )

        # Append incoming subsequent messages
        incoming_subsequent = incoming_messages[last_snapshot.message_count :]
        repaired.extend(incoming_subsequent)

        # If any mutations were rolled back, append delta note to tail
        if delta_notes:
            note_content = "\n".join(delta_notes)
            repaired.append(self.create_delta_correction_message(last_snapshot.message_count - 1, note_content))

        repair_result = AppendOnlyEnforcementResult(
            is_valid_append_only=True,
            appended_message_count=len(repaired) - last_snapshot.message_count,
            violations=validation.violations,
            diagnostic_message=(
                f"Repaired transcript: Restored {last_snapshot.message_count} historical messages to "
                "pristine snapshot and converted in-place mutations into tail delta evolution."
            ),
        )

        return tuple(repaired), repair_result

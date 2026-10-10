"""Adoption and disambiguation engine for SQLite transcript projection.

[INPUT]
- SessionMessage list, TranscriptEntry list, and timestamp tolerance in milliseconds.

[OUTPUT]
- AdoptionDecision list mapping session messages to transcript entries or fail-closed unstamped states.

[POS]
- Core disambiguation engine for Item 150 SqliteTranscriptProjectionSuite.
"""

from __future__ import annotations

from collections import defaultdict

from .models import AdoptionDecision, AdoptionStatus, SessionMessage, TranscriptEntry


class TranscriptAdoptionEngine:
    """Reconciles session messages against transcript entries with duplicate disambiguation.

    Guarantees:
    1. Genuinely unique content adopts without requiring timestamps.
    2. Repeated bodies adopt by created time proximity within tolerance_ms.
    3. Same-second twins with identical timestamps fail-closed (remain unstamped).
    4. Unknown or invalid timestamps on repeated bodies fail-closed (remain unstamped).
    """

    def __init__(self, default_tolerance_ms: int = 2000) -> None:
        self._default_tolerance_ms = default_tolerance_ms

    def reconcile(
        self,
        messages: list[SessionMessage],
        entries: list[TranscriptEntry],
        tolerance_ms: int | None = None,
    ) -> list[AdoptionDecision]:
        """Reconcile session messages against transcript candidates with strict fail-closed guards."""
        tol = self._default_tolerance_ms if tolerance_ms is None else tolerance_ms

        entries_by_content: dict[str, list[TranscriptEntry]] = defaultdict(list)
        for entry in entries:
            entries_by_content[entry.content].append(entry)

        messages_by_content: dict[str, list[SessionMessage]] = defaultdict(list)
        for msg in messages:
            messages_by_content[msg.content].append(msg)

        allocated_entry_ids: set[str] = set()
        decisions: list[AdoptionDecision] = []

        for msg in messages:
            candidates = [
                e
                for e in entries_by_content.get(msg.content, [])
                if e.entry_id not in allocated_entry_ids
            ]

            # Case 1: No candidates exist for this content
            if not candidates:
                decisions.append(
                    AdoptionDecision(
                        message_id=msg.message_id,
                        transcript_entry_id=None,
                        status=AdoptionStatus.UNSTAMPED_NO_MATCH,
                        reason="No transcript entry found with matching content.",
                    )
                )
                continue

            # Case 2: Genuinely unique content in both messages and transcript entries
            total_content_msgs = len(messages_by_content.get(msg.content, []))
            total_content_entries = len(entries_by_content.get(msg.content, []))
            if total_content_msgs == 1 and total_content_entries == 1:
                single_entry = candidates[0]
                allocated_entry_ids.add(single_entry.entry_id)
                decisions.append(
                    AdoptionDecision(
                        message_id=msg.message_id,
                        transcript_entry_id=single_entry.entry_id,
                        status=AdoptionStatus.ADOPTED_UNIQUE,
                        reason="Genuinely unique content adopted without timestamp requirement.",
                    )
                )
                continue

            # Case 3: Repeated bodies - check for unknown timestamp
            if msg.timestamp_ms is None:
                decisions.append(
                    AdoptionDecision(
                        message_id=msg.message_id,
                        transcript_entry_id=None,
                        status=AdoptionStatus.UNSTAMPED_UNKNOWN_TIME,
                        reason="Repeated content requires timestamp; message timestamp is missing.",
                    )
                )
                continue

            # Filter candidates with valid created_at_ms within tolerance
            valid_candidates: list[tuple[TranscriptEntry, int]] = []
            has_unknown_candidate_time = False

            for cand in candidates:
                if cand.created_at_ms is None:
                    has_unknown_candidate_time = True
                    continue
                diff = abs(cand.created_at_ms - msg.timestamp_ms)
                if diff <= tol:
                    valid_candidates.append((cand, diff))

            if has_unknown_candidate_time and not valid_candidates:
                decisions.append(
                    AdoptionDecision(
                        message_id=msg.message_id,
                        transcript_entry_id=None,
                        status=AdoptionStatus.UNSTAMPED_UNKNOWN_TIME,
                        reason="Competing candidates contain unknown timestamps; fail-closed.",
                    )
                )
                continue

            if not valid_candidates:
                decisions.append(
                    AdoptionDecision(
                        message_id=msg.message_id,
                        transcript_entry_id=None,
                        status=AdoptionStatus.UNSTAMPED_NO_MATCH,
                        reason="No candidates within timestamp tolerance window.",
                    )
                )
                continue

            # Sort by absolute time delta
            valid_candidates.sort(key=lambda item: item[1])

            # Case 4: Same-second twin conflict check
            if len(valid_candidates) >= 2:
                first_diff = valid_candidates[0][1]
                second_diff = valid_candidates[1][1]
                # If both are equally close or share identical timestamps, ambiguity cannot be resolved
                cand1_time = valid_candidates[0][0].created_at_ms
                cand2_time = valid_candidates[1][0].created_at_ms
                if cand1_time == cand2_time or first_diff == second_diff:
                    decisions.append(
                        AdoptionDecision(
                            message_id=msg.message_id,
                            transcript_entry_id=None,
                            status=AdoptionStatus.UNSTAMPED_TWIN_CONFLICT,
                            reason="Same-second twin ambiguity detected; fail-closed unstamped.",
                        )
                    )
                    continue

            # Case 5: Clear closest candidate adopted
            best_entry = valid_candidates[0][0]
            allocated_entry_ids.add(best_entry.entry_id)
            decisions.append(
                AdoptionDecision(
                    message_id=msg.message_id,
                    transcript_entry_id=best_entry.entry_id,
                    status=AdoptionStatus.ADOPTED_BY_TIMESTAMP,
                    reason=f"Adopted repeated body by created time proximity ({valid_candidates[0][1]}ms diff).",
                )
            )

        return decisions

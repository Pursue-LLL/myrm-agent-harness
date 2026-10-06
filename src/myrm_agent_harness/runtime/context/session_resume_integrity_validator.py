"""Session state write-failure self-healing and resume integrity validator.

[INPUT]
- turns/events: Sequence of SessionTurnRecord to inspect before resuming a run

[OUTPUT]
- AnomalyKind: Classification of session persistence anomalies (sequence gap, unclosed tool, etc.)
- IntegrityAnomaly: Structured description of an identified write anomaly
- SessionTurnRecord: Lightweight normalized record model for session history
- SessionResumeIntegrityReport: Comprehensive pre-execution resume integrity verdict
- SessionResumeValidator: Core validator asserting integrity and applying write compensations

[POS]
Harness runtime context layer. Pre-execution safety gate asserting session state
persistence integrity before resuming runs, compensating partial writes automatically.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

_RESUME_COMPENSATION_PLACEHOLDER = (
    "[Resume Compensation: Tool execution or write interrupted prior to persistence; auto-closed on resume]"
)


class AnomalyKind(StrEnum):
    """Categorization of session persistence anomalies."""

    SEQUENCE_GAP = "sequence_gap"
    UNCLOSED_TOOL_CALL = "unclosed_tool_call"
    PARTIAL_TURN_RECORD = "partial_turn_record"
    CORRUPTED_METADATA = "corrupted_metadata"


@dataclass(slots=True, frozen=True)
class IntegrityAnomaly:
    """Diagnostic detail of a detected persistence anomaly."""

    anomaly_id: str
    kind: AnomalyKind
    description: str
    target_turn_or_seq: int
    repairable: bool


@dataclass(slots=True, frozen=True)
class SessionTurnRecord:
    """Normalized turn record for session resume verification."""

    turn_id: str
    turn_index: int
    role: str
    content: str
    tool_call_ids: list[str] = field(default_factory=list)
    tool_result_id: str | None = None
    status: str = "completed"


@dataclass(slots=True, frozen=True)
class SessionResumeIntegrityReport:
    """Verdict on session resume safety and auto-healing modifications."""

    session_id: str
    is_valid: bool
    can_resume: bool
    auto_healed: bool
    anomalies: list[IntegrityAnomaly]
    repaired_count: int
    validation_timestamp_iso: str


class SessionResumeValidator:
    """Pre-execution assertion engine detecting and compensating partial session writes."""

    @classmethod
    def validate_and_heal(
        cls,
        session_id: str,
        turns: Sequence[SessionTurnRecord],
    ) -> tuple[list[SessionTurnRecord], SessionResumeIntegrityReport]:
        """Assert session integrity before resuming run, auto-healing repairable anomalies."""
        now_iso = datetime.now(UTC).isoformat()
        if not turns:
            report = SessionResumeIntegrityReport(
                session_id=session_id,
                is_valid=True,
                can_resume=True,
                auto_healed=False,
                anomalies=[],
                repaired_count=0,
                validation_timestamp_iso=now_iso,
            )
            return [], report

        healed_turns = list(turns)
        anomalies: list[IntegrityAnomaly] = []
        repaired_count = 0

        # Phase 1: Detect and repair sequence index drift/gaps
        expected_seq = healed_turns[0].turn_index
        resequenced: list[SessionTurnRecord] = []
        for idx, turn in enumerate(healed_turns):
            if turn.turn_index != expected_seq:
                anomalies.append(
                    IntegrityAnomaly(
                        anomaly_id=f"anom_{uuid.uuid4().hex[:8]}",
                        kind=AnomalyKind.SEQUENCE_GAP,
                        description=f"Turn sequence gap detected at item {idx}: expected {expected_seq}, found {turn.turn_index}",
                        target_turn_or_seq=turn.turn_index,
                        repairable=True,
                    )
                )
                resequenced.append(
                    SessionTurnRecord(
                        turn_id=turn.turn_id,
                        turn_index=expected_seq,
                        role=turn.role,
                        content=turn.content,
                        tool_call_ids=list(turn.tool_call_ids),
                        tool_result_id=turn.tool_result_id,
                        status=turn.status,
                    )
                )
                repaired_count += 1
            else:
                resequenced.append(turn)
            expected_seq += 1

        healed_turns = resequenced

        # Phase 2: Detect and compensate unclosed tool calls (e.g. process crash mid-tool)
        resolved_results: set[str] = {
            t.tool_result_id for t in healed_turns if t.role == "tool" and t.tool_result_id
        }

        compensated_turns: list[SessionTurnRecord] = []
        pending_tool_calls: list[str] = []

        for turn in healed_turns:
            if turn.role != "tool" and pending_tool_calls:
                # Flush missing tool compensations for the previous assistant batch
                for call_id in pending_tool_calls:
                    anomalies.append(
                        IntegrityAnomaly(
                            anomaly_id=f"anom_{uuid.uuid4().hex[:8]}",
                            kind=AnomalyKind.UNCLOSED_TOOL_CALL,
                            description=f"Unclosed tool call {call_id} without persisted result; injecting compensation",
                            target_turn_or_seq=compensated_turns[-1].turn_index,
                            repairable=True,
                        )
                    )
                    compensated_turns.append(
                        SessionTurnRecord(
                            turn_id=f"comp_{uuid.uuid4().hex[:8]}",
                            turn_index=compensated_turns[-1].turn_index + 1,
                            role="tool",
                            content=_RESUME_COMPENSATION_PLACEHOLDER,
                            tool_result_id=call_id,
                            status="interrupted_resumed",
                        )
                    )
                    resolved_results.add(call_id)
                    repaired_count += 1
                pending_tool_calls.clear()

            compensated_turns.append(turn)

            if turn.role == "assistant" and turn.tool_call_ids:
                for call_id in turn.tool_call_ids:
                    if call_id not in resolved_results:
                        pending_tool_calls.append(call_id)
            elif turn.role == "tool" and turn.tool_result_id in pending_tool_calls:
                pending_tool_calls.remove(turn.tool_result_id)

        # Flush any trailing unclosed tool calls at end of session
        for call_id in pending_tool_calls:
            anomalies.append(
                IntegrityAnomaly(
                    anomaly_id=f"anom_{uuid.uuid4().hex[:8]}",
                    kind=AnomalyKind.UNCLOSED_TOOL_CALL,
                    description=f"Unclosed tool call {call_id} at session tail without persisted result; injecting compensation",
                    target_turn_or_seq=compensated_turns[-1].turn_index if compensated_turns else 0,
                    repairable=True,
                )
            )
            prev_idx = compensated_turns[-1].turn_index if compensated_turns else 0
            compensated_turns.append(
                SessionTurnRecord(
                    turn_id=f"comp_{uuid.uuid4().hex[:8]}",
                    turn_index=prev_idx + 1,
                    role="tool",
                    content=_RESUME_COMPENSATION_PLACEHOLDER,
                    tool_result_id=call_id,
                    status="interrupted_resumed",
                )
            )
            resolved_results.add(call_id)
            repaired_count += 1

        # Phase 3: Check for pending/incomplete status in final turn
        final_turns: list[SessionTurnRecord] = []
        for turn in compensated_turns:
            if turn.status == "pending":
                anomalies.append(
                    IntegrityAnomaly(
                        anomaly_id=f"anom_{uuid.uuid4().hex[:8]}",
                        kind=AnomalyKind.PARTIAL_TURN_RECORD,
                        description=f"Turn {turn.turn_index} was left in 'pending' state; finalizing as 'interrupted_resumed'",
                        target_turn_or_seq=turn.turn_index,
                        repairable=True,
                    )
                )
                final_turns.append(
                    SessionTurnRecord(
                        turn_id=turn.turn_id,
                        turn_index=turn.turn_index,
                        role=turn.role,
                        content=turn.content,
                        tool_call_ids=list(turn.tool_call_ids),
                        tool_result_id=turn.tool_result_id,
                        status="interrupted_resumed",
                    )
                )
                repaired_count += 1
            else:
                final_turns.append(turn)

        # Normalize sequential numbering post-injection
        normalized_final: list[SessionTurnRecord] = []
        for idx, turn in enumerate(final_turns):
            if turn.turn_index != idx:
                normalized_final.append(
                    SessionTurnRecord(
                        turn_id=turn.turn_id,
                        turn_index=idx,
                        role=turn.role,
                        content=turn.content,
                        tool_call_ids=list(turn.tool_call_ids),
                        tool_result_id=turn.tool_result_id,
                        status=turn.status,
                    )
                )
            else:
                normalized_final.append(turn)

        is_valid = len(anomalies) == 0
        auto_healed = repaired_count > 0
        can_resume = all(a.repairable for a in anomalies)

        report = SessionResumeIntegrityReport(
            session_id=session_id,
            is_valid=is_valid,
            can_resume=can_resume,
            auto_healed=auto_healed,
            anomalies=anomalies,
            repaired_count=repaired_count,
            validation_timestamp_iso=now_iso,
        )

        return normalized_final, report

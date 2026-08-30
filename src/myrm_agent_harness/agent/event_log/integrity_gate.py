"""Event Log Integrity Gate — Session enclosure and anti-silent-corruption verification.

[INPUT]
- myrm_agent_harness.observability.invariants.types::(InvariantViolation, InvariantSeverity) (POS: 不变式基础契约)
- myrm_agent_harness.observability.invariants.registry::(RuntimeInvariantRegistry, InvariantError, default_invariant_registry) (POS: 不变式注册中心)

[OUTPUT]
- verify_session_enclosure: Asserts events are bounded within legal Step/Turn brackets
- verify_sequence_continuity: Asserts monotonic timestamps and sequence continuity
- assert_log_integrity: Gatekeeper enforcing zero silent corruption on log streams
- install_log_integrity_invariants: Companion installer for invariant registry

[POS]
Zero-LLM deterministic integrity gate protecting event log replay and multi-turn context reconstruction.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from myrm_agent_harness.observability.invariants.registry import (
    InvariantError,
    InvariantMode,
    RuntimeInvariantRegistry,
    default_invariant_registry,
)
from myrm_agent_harness.observability.invariants.types import (
    InvariantSeverity,
    InvariantViolation,
)

logger = logging.getLogger(__name__)

# Events that are legal top-level lifecycle demarcators or system checkpoints
_TOP_LEVEL_LEGAL_TYPES = frozenset(
    {
        "session_start",
        "session_end",
        "checkpoint",
        "state_snapshot",
        "diagnostic",
        "turn_start",
        "step_start",
        "user_message",
    }
)


def verify_session_enclosure(events: Sequence[object]) -> list[InvariantViolation]:
    """Verify that execution events (tool calls, intermediate messages) are enclosed within legal turn/step brackets.

    Orphan assistant/tool messages occurring outside an active turn/step bracket are reported.
    """
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        return []

    violations: list[InvariantViolation] = []
    in_active_step = False
    current_step_id: str | None = None

    for idx, raw_evt in enumerate(events):
        evt_dict: Mapping[str, object]
        if isinstance(raw_evt, Mapping):
            evt_dict = raw_evt
        elif hasattr(raw_evt, "model_dump"):
            evt_dict = raw_evt.model_dump()
        elif hasattr(raw_evt, "__dict__"):
            evt_dict = raw_evt.__dict__
        else:
            continue

        evt_type = str(
            evt_dict.get("event_type")
            or evt_dict.get("type")
            or evt_dict.get("kind")
            or ""
        )
        step_id = str(evt_dict.get("step_id") or evt_dict.get("step_key") or "")

        if evt_type in ("step_start", "turn_start", "task_step_start"):
            in_active_step = True
            current_step_id = step_id or f"step_{idx}"
        elif evt_type in ("step_end", "turn_end", "task_step_end", "session_end"):
            in_active_step = False
            current_step_id = None
        elif evt_type in ("tool_start", "tool_call", "tool_result", "tool_end", "tool_failure"):
            if not in_active_step:
                violations.append(
                    InvariantViolation(
                        package_name="event_log.integrity",
                        invariant_name="session_enclosure",
                        message=(
                            f"Orphan tool event '{evt_type}' detected at index {idx} "
                            "without an active enclosing step/turn bracket."
                        ),
                        severity=InvariantSeverity.ERROR,
                        details={"index": idx, "event_type": evt_type, "event": dict(evt_dict)},
                    )
                )

    return violations


def verify_sequence_continuity(events: Sequence[object]) -> list[InvariantViolation]:
    """Verify timestamps and sequence indexes are monotonically non-decreasing without corruption gaps."""
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        return []

    violations: list[InvariantViolation] = []
    last_timestamp: float = -1.0
    last_seq: int = -1

    for idx, raw_evt in enumerate(events):
        evt_dict: Mapping[str, object]
        if isinstance(raw_evt, Mapping):
            evt_dict = raw_evt
        elif hasattr(raw_evt, "model_dump"):
            evt_dict = raw_evt.model_dump()
        elif hasattr(raw_evt, "__dict__"):
            evt_dict = raw_evt.__dict__
        else:
            continue

        # 1. Monotonic timestamp check
        raw_ts = evt_dict.get("timestamp") or evt_dict.get("created_at") or evt_dict.get("time")
        if raw_ts is not None:
            try:
                ts = float(raw_ts)
                if last_timestamp >= 0.0 and ts < (last_timestamp - 1.0):  # 1s tolerance for minor clock skew
                    violations.append(
                        InvariantViolation(
                            package_name="event_log.integrity",
                            invariant_name="sequence_continuity",
                            message=(
                                f"Timestamp regression detected at event index {idx}: "
                                f"current {ts} < previous {last_timestamp}"
                            ),
                            severity=InvariantSeverity.WARN,
                            details={"index": idx, "current_ts": ts, "last_ts": last_timestamp},
                        )
                    )
                last_timestamp = max(last_timestamp, ts)
            except (ValueError, TypeError):
                pass

        # 2. Sequence continuity check (if seq / sequence exists)
        raw_seq = evt_dict.get("seq")
        if raw_seq is None:
            raw_seq = evt_dict.get("sequence")
        if raw_seq is None:
            raw_seq = evt_dict.get("sequence_number")

        if raw_seq is not None:
            try:
                seq = int(raw_seq)
                if last_seq >= 0 and seq != (last_seq + 1):
                    violations.append(
                        InvariantViolation(
                            package_name="event_log.integrity",
                            invariant_name="sequence_continuity",
                            message=(
                                f"Sequence gap/jump detected at event index {idx}: "
                                f"expected {last_seq + 1}, got {seq}"
                            ),
                            severity=InvariantSeverity.ERROR,
                            details={"index": idx, "expected_seq": last_seq + 1, "actual_seq": seq},
                        )
                    )
                last_seq = seq
            except (ValueError, TypeError):
                pass

    return violations


def assert_log_integrity(
    events: Sequence[object],
    *,
    strict: bool = False,
) -> list[InvariantViolation]:
    """Execute full log enclosure and sequence continuity assertions on an event log stream.

    Args:
        events: The sequence of StructuredEvent or event mapping objects.
        strict: If True, immediately raises InvariantError on the first ERROR violation.

    Returns:
        List of all detected InvariantViolations.
    """
    violations: list[InvariantViolation] = []
    violations.extend(verify_session_enclosure(events))
    violations.extend(verify_sequence_continuity(events))

    if strict:
        for v in violations:
            if v.severity == InvariantSeverity.ERROR:
                raise InvariantError(v)

    return violations


def install_log_integrity_invariants(registry: RuntimeInvariantRegistry | None = None) -> None:
    """Register session enclosure and sequence continuity checks into the runtime invariant registry."""
    target_registry = registry or default_invariant_registry
    target_registry.register("event_log.integrity", "session_enclosure", verify_session_enclosure)
    target_registry.register("event_log.integrity", "sequence_continuity", verify_sequence_continuity)

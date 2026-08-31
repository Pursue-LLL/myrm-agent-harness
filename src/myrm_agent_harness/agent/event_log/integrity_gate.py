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
Single source of truth for step/turn enclosure and sequence continuity checks.
"""

from __future__ import annotations

import logging
from typing import Mapping, Sequence

from myrm_agent_harness.observability.invariants.registry import (
    InvariantError,
    RuntimeInvariantRegistry,
    default_invariant_registry,
)
from myrm_agent_harness.observability.invariants.types import (
    InvariantSeverity,
    InvariantViolation,
)

logger = logging.getLogger(__name__)

_PACKAGE = "event_log.integrity"

_STEP_OPEN_TYPES = frozenset({"task_step_start", "step_start", "turn_start", "session_start"})
_STEP_CLOSE_TYPES = frozenset({"task_step_end", "step_end", "turn_end", "session_end"})
_ENCLOSED_REQUIRED_TYPES = frozenset(
    {
        "tool_start",
        "tool_call",
        "tool_end",
        "tool_result",
        "tool_failure",
        "thought",
        "thinking",
        "model_output",
        "llm_call",
        "user_message",
        "assistant_message",
    }
)


def _event_to_mapping(raw_evt: object) -> Mapping[str, object] | None:
    if isinstance(raw_evt, Mapping):
        return raw_evt
    if hasattr(raw_evt, "model_dump"):
        return raw_evt.model_dump()
    if hasattr(raw_evt, "__dict__"):
        return raw_evt.__dict__
    return None


def _event_type(evt_dict: Mapping[str, object]) -> str | None:
    raw = evt_dict.get("event_type") or evt_dict.get("type") or evt_dict.get("kind")
    return str(raw) if isinstance(raw, str) else (str(raw) if raw is not None else None)


def verify_session_enclosure(events: Sequence[object]) -> list[InvariantViolation]:
    """Verify events are strictly enclosed within Step/Turn brackets."""
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        return []

    violations: list[InvariantViolation] = []
    active_steps: list[dict[str, object]] = []

    for idx, raw_evt in enumerate(events):
        evt_dict = _event_to_mapping(raw_evt)
        if evt_dict is None:
            continue

        event_type = _event_type(evt_dict)
        if not event_type:
            continue

        if event_type in _STEP_OPEN_TYPES:
            active_steps.append(
                {
                    "index": idx,
                    "event_type": event_type,
                    "step_id": evt_dict.get("step_id") or evt_dict.get("turn_id") or evt_dict.get("id"),
                }
            )
        elif event_type in _STEP_CLOSE_TYPES:
            if active_steps:
                active_steps.pop()
            else:
                violations.append(
                    InvariantViolation(
                        package_name=_PACKAGE,
                        invariant_name="session_enclosure",
                        message=(
                            f"Orphan closing bracket '{event_type}' encountered at index {idx} "
                            "without matching start step/turn bracket."
                        ),
                        severity=InvariantSeverity.ERROR,
                        details={"index": idx, "event_type": event_type},
                    )
                )
        elif event_type in _ENCLOSED_REQUIRED_TYPES:
            if not active_steps:
                violations.append(
                    InvariantViolation(
                        package_name=_PACKAGE,
                        invariant_name="session_enclosure",
                        message=(
                            f"Payload event '{event_type}' at index {idx} occurs outside an active step/turn enclosure."
                        ),
                        severity=InvariantSeverity.ERROR,
                        details={"index": idx, "event_type": event_type},
                    )
                )

    for unclosed in active_steps:
        violations.append(
            InvariantViolation(
                package_name=_PACKAGE,
                invariant_name="session_enclosure",
                message=(
                    f"Unclosed step bracket '{unclosed.get('event_type')}' started at index {unclosed.get('index')} "
                    "never received closing bracket."
                ),
                severity=InvariantSeverity.WARN,
                details=unclosed,
            )
        )

    return violations


def verify_sequence_continuity(events: Sequence[object]) -> list[InvariantViolation]:
    """Verify sequence numbers are monotonic gap-free and timestamps non-regressing."""
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        return []

    violations: list[InvariantViolation] = []
    last_timestamp: float = -1.0
    last_seq: int | None = None
    last_idx: int | None = None

    for idx, raw_evt in enumerate(events):
        evt_dict = _event_to_mapping(raw_evt)
        if evt_dict is None:
            continue

        raw_ts = evt_dict.get("timestamp") or evt_dict.get("created_at") or evt_dict.get("time") or evt_dict.get("ts")
        if raw_ts is not None:
            try:
                ts = float(raw_ts)
                if last_timestamp >= 0.0 and ts < (last_timestamp - 1.0):
                    violations.append(
                        InvariantViolation(
                            package_name=_PACKAGE,
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

        raw_seq = evt_dict.get("seq") if "seq" in evt_dict else evt_dict.get("sequence")
        if raw_seq is None:
            raw_seq = evt_dict.get("sequence_number")
        if raw_seq is None:
            continue

        try:
            seq = int(raw_seq)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            violations.append(
                InvariantViolation(
                    package_name=_PACKAGE,
                    invariant_name="sequence_continuity",
                    message=f"Non-integer sequence number '{raw_seq}' at event index {idx}.",
                    severity=InvariantSeverity.ERROR,
                    details={"index": idx, "raw_seq": raw_seq},
                )
            )
            continue

        if last_seq is not None:
            if seq <= last_seq:
                violations.append(
                    InvariantViolation(
                        package_name=_PACKAGE,
                        invariant_name="sequence_continuity",
                        message=(
                            f"Non-monotonic sequence number at index {idx}: current seq={seq} <= previous seq={last_seq} "
                            f"(at index {last_idx})."
                        ),
                        severity=InvariantSeverity.ERROR,
                        details={"index": idx, "seq": seq, "previous_seq": last_seq, "previous_index": last_idx},
                    )
                )
            elif seq > last_seq + 1:
                violations.append(
                    InvariantViolation(
                        package_name=_PACKAGE,
                        invariant_name="sequence_continuity",
                        message=(
                            f"Sequence gap detected at index {idx}: jumped from seq={last_seq} (at index {last_idx}) "
                            f"to seq={seq} (gap of {seq - last_seq - 1} missing events)."
                        ),
                        severity=InvariantSeverity.ERROR,
                        details={
                            "index": idx,
                            "seq": seq,
                            "previous_seq": last_seq,
                            "gap_size": seq - last_seq - 1,
                            "previous_index": last_idx,
                        },
                    )
                )

        last_seq = seq
        last_idx = idx

    return violations


def assert_log_integrity(
    events: Sequence[object],
    *,
    strict: bool = False,
) -> list[InvariantViolation]:
    """Execute full log enclosure and sequence continuity assertions on an event log stream."""
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
    target_registry.register(_PACKAGE, "session_enclosure", verify_session_enclosure)
    target_registry.register(_PACKAGE, "sequence_continuity", verify_sequence_continuity)

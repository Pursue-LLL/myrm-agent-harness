"""Built-in Core Invariant Pack (Session Event Pairing, State Machine, Todo Integrity, Step Enclosure, Sequence Continuity).

[INPUT]
- myrm_agent_harness.observability.invariants.types::(InvariantViolation, InvariantSeverity) (POS: 不变式基础类型)
- myrm_agent_harness.observability.invariants.registry::(RuntimeInvariantRegistry, default_invariant_registry) (POS: 不变式注册中心)

[OUTPUT]
- check_session_event_pairing: Asserts tool_start and tool_end/failure pairs in event stream
- check_agent_state_transition: Asserts valid state transitions according to lifecycle DAG
- check_todo_structure_integrity: Asserts Todo list items have unique IDs, valid status, and proper parent linkage
- check_step_enclosure: Asserts events strictly enclosed within Step/Turn brackets
- check_sequence_continuity: Asserts sequence numbers are strictly monotonic and gap-free
- install_core_invariants: Installs standard companion checks into the target registry

[POS]
Production-grade default runtime invariant checks protecting event pairing, status flow, task state, step enclosure, and log continuity.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from myrm_agent_harness.observability.invariants.registry import (
    RuntimeInvariantRegistry,
    default_invariant_registry,
)
from myrm_agent_harness.observability.invariants.types import (
    InvariantSeverity,
    InvariantViolation,
)

# ---------------------------------------------------------------------------
# 1. Session Event Pairing Invariant
# ---------------------------------------------------------------------------


def check_session_event_pairing(context: object) -> list[InvariantViolation]:
    """Verify tool_start events have matching terminal events (tool_end / tool_failure).

    Context format expectation: Sequence of mapping objects (or objects with event_type/type and tool_call_id).
    """
    if not isinstance(context, Sequence):
        return []

    violations: list[InvariantViolation] = []
    open_tool_calls: dict[str, dict[str, object]] = {}

    for idx, raw_event in enumerate(context):
        if not isinstance(raw_event, Mapping):
            continue

        event_type = raw_event.get("event_type") or raw_event.get("type") or raw_event.get("kind")
        tool_call_id = raw_event.get("tool_call_id") or raw_event.get("call_id") or raw_event.get("id")

        if not isinstance(event_type, str):
            continue

        str_call_id = str(tool_call_id) if tool_call_id is not None else f"anon_step_{idx}"

        if event_type in ("tool_start", "tool_call", "task_step_start"):
            open_tool_calls[str_call_id] = {
                "index": idx,
                "tool_name": raw_event.get("tool_name", "unknown"),
                "event_type": event_type,
            }
        elif event_type in ("tool_end", "tool_result", "tool_failure", "task_step_end"):
            if str_call_id in open_tool_calls:
                open_tool_calls.pop(str_call_id)
            elif tool_call_id is not None:
                # Terminal event without prior start
                violations.append(
                    InvariantViolation(
                        package_name="session.events",
                        invariant_name="session_event_pairing",
                        message=(
                            f"Orphan terminal event '{event_type}' encountered at index {idx} "
                            f"without matching start event (tool_call_id='{str_call_id}')"
                        ),
                        severity=InvariantSeverity.WARN,
                        details={"index": idx, "tool_call_id": str_call_id, "event_type": event_type},
                    )
                )

    # Check for unclosed / dangling tool calls
    for unclosed_id, meta in open_tool_calls.items():
        violations.append(
            InvariantViolation(
                package_name="session.events",
                invariant_name="session_event_pairing",
                message=(
                    f"Unclosed tool call '{meta.get('tool_name')}' started at event index {meta.get('index')} "
                    f"(tool_call_id='{unclosed_id}') never received terminal event."
                ),
                severity=InvariantSeverity.ERROR,
                details={"tool_call_id": unclosed_id, **meta},
            )
        )

    return violations


# ---------------------------------------------------------------------------
# 2. Agent State Machine Transition Invariant
# ---------------------------------------------------------------------------

_VALID_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"INITIALIZING", "IDLE", "RUNNING", "FAILED"}),
    "INITIALIZING": frozenset({"IDLE", "RUNNING", "FAILED"}),
    "IDLE": frozenset({"RUNNING", "PAUSED", "COMPLETED", "FAILED"}),
    "RUNNING": frozenset({"RUNNING", "PAUSED", "COMPLETED", "FAILED", "WAITING_INPUT"}),
    "WAITING_INPUT": frozenset({"RUNNING", "PAUSED", "COMPLETED", "FAILED"}),
    "PAUSED": frozenset({"RUNNING", "COMPLETED", "FAILED"}),
    # Terminal states can transition to CREATED or IDLE on session reset, but not directly to RUNNING
    "COMPLETED": frozenset({"IDLE", "CREATED"}),
    "FAILED": frozenset({"IDLE", "CREATED"}),
}


def check_agent_state_transition(context: object) -> list[InvariantViolation]:
    """Verify state machine transition validity against valid DAG rules.

    Context expectation: Dict with 'from_state' and 'to_state' or tuple of (from_state, to_state).
    """
    from_state: str | None = None
    to_state: str | None = None

    if isinstance(context, Mapping):
        from_raw = context.get("from_state") or context.get("previous_state") or context.get("current_state")
        to_raw = context.get("to_state") or context.get("next_state") or context.get("target_state")
        from_state = str(from_raw).upper() if from_raw else None
        to_state = str(to_raw).upper() if to_raw else None
    elif isinstance(context, (tuple, list)) and len(context) >= 2:
        from_state = str(context[0]).upper()
        to_state = str(context[1]).upper()

    if not from_state or not to_state:
        return []

    valid_targets = _VALID_STATE_TRANSITIONS.get(from_state)
    if valid_targets is None:
        return [
            InvariantViolation(
                package_name="agent.lifecycle",
                invariant_name="agent_state_transition",
                message=f"Unknown origin state '{from_state}' during transition to '{to_state}'.",
                severity=InvariantSeverity.ERROR,
                details={"from_state": from_state, "to_state": to_state},
            )
        ]

    if to_state not in valid_targets:
        return [
            InvariantViolation(
                package_name="agent.lifecycle",
                invariant_name="agent_state_transition",
                message=(
                    f"Illegal state transition from terminal/invalid '{from_state}' to '{to_state}'. "
                    f"Allowed targets: {sorted(list(valid_targets))}"
                ),
                severity=InvariantSeverity.ERROR,
                details={"from_state": from_state, "to_state": to_state, "allowed": list(valid_targets)},
            )
        ]

    return []


# ---------------------------------------------------------------------------
# 3. Todo Structure Integrity Invariant
# ---------------------------------------------------------------------------

_VALID_TODO_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled"})


def check_todo_structure_integrity(context: object) -> list[InvariantViolation]:
    """Verify Todo list structure integrity (unique IDs, valid status, non-empty content).

    Context expectation: Sequence of mapping objects (or Todo models).
    """
    if not isinstance(context, Sequence) or isinstance(context, (str, bytes)):
        return []

    violations: list[InvariantViolation] = []
    seen_ids: set[str] = set()

    for idx, item in enumerate(context):
        if not isinstance(item, Mapping):
            continue

        raw_id = item.get("id")
        content = item.get("content")
        status = item.get("status")

        # 1. Check ID presence & uniqueness
        if not raw_id or not str(raw_id).strip():
            violations.append(
                InvariantViolation(
                    package_name="toolkits.todo",
                    invariant_name="todo_structure_integrity",
                    message=f"Todo item at index {idx} has missing or empty id.",
                    severity=InvariantSeverity.ERROR,
                    details={"index": idx, "item": dict(item)},
                )
            )
        else:
            str_id = str(raw_id).strip()
            if str_id in seen_ids:
                violations.append(
                    InvariantViolation(
                        package_name="toolkits.todo",
                        invariant_name="todo_structure_integrity",
                        message=f"Duplicate Todo ID '{str_id}' detected at index {idx}.",
                        severity=InvariantSeverity.ERROR,
                        details={"index": idx, "id": str_id},
                    )
                )
            seen_ids.add(str_id)

        # 2. Check Content presence
        if not content or not str(content).strip():
            violations.append(
                InvariantViolation(
                    package_name="toolkits.todo",
                    invariant_name="todo_structure_integrity",
                    message=f"Todo item '{raw_id or idx}' has missing or empty content.",
                    severity=InvariantSeverity.WARN,
                    details={"index": idx, "id": str(raw_id)},
                )
            )

        # 3. Check Status legality
        if status and str(status).lower() not in _VALID_TODO_STATUSES:
            violations.append(
                InvariantViolation(
                    package_name="toolkits.todo",
                    invariant_name="todo_structure_integrity",
                    message=f"Todo item '{raw_id or idx}' has invalid status '{status}'.",
                    severity=InvariantSeverity.ERROR,
                    details={"index": idx, "status": str(status), "allowed": list(_VALID_TODO_STATUSES)},
                )
            )

    return violations


# ---------------------------------------------------------------------------
# 4. Step Enclosure Invariant (Synthetic Log Anti-Silent-Corruption)
# ---------------------------------------------------------------------------

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


def check_step_enclosure(context: object) -> list[InvariantViolation]:
    """Verify events are strictly enclosed within Step/Turn brackets.

    Orphan payload events outside a step or unclosed step brackets are flagged as violations.
    Context expectation: Sequence of mapping objects (or objects with event_type/type/kind).
    """
    if not isinstance(context, Sequence) or isinstance(context, (str, bytes)):
        return []

    violations: list[InvariantViolation] = []
    active_steps: list[dict[str, object]] = []

    for idx, raw_event in enumerate(context):
        if not isinstance(raw_event, Mapping):
            continue

        event_type = raw_event.get("event_type") or raw_event.get("type") or raw_event.get("kind")
        if not isinstance(event_type, str):
            continue

        if event_type in _STEP_OPEN_TYPES:
            active_steps.append(
                {
                    "index": idx,
                    "event_type": event_type,
                    "step_id": raw_event.get("step_id") or raw_event.get("turn_id") or raw_event.get("id"),
                }
            )
        elif event_type in _STEP_CLOSE_TYPES:
            if active_steps:
                active_steps.pop()
            else:
                violations.append(
                    InvariantViolation(
                        package_name="session.events",
                        invariant_name="step_enclosure",
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
                        package_name="session.events",
                        invariant_name="step_enclosure",
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
                package_name="session.events",
                invariant_name="step_enclosure",
                message=(
                    f"Unclosed step bracket '{unclosed.get('event_type')}' started at index {unclosed.get('index')} "
                    "never received closing bracket."
                ),
                severity=InvariantSeverity.WARN,
                details=unclosed,
            )
        )

    return violations


# ---------------------------------------------------------------------------
# 5. Sequence Continuity Invariant (Monotonic & Gap-Free Audit)
# ---------------------------------------------------------------------------


def check_sequence_continuity(context: object) -> list[InvariantViolation]:
    """Verify event sequence numbers are strictly monotonically increasing without gaps.

    Context expectation: Sequence of mapping objects (or objects with seq/sequence).
    """
    if not isinstance(context, Sequence) or isinstance(context, (str, bytes)):
        return []

    violations: list[InvariantViolation] = []
    last_seq: int | None = None
    last_idx: int | None = None

    for idx, raw_event in enumerate(context):
        if not isinstance(raw_event, Mapping):
            continue

        raw_seq = raw_event.get("seq") if "seq" in raw_event else raw_event.get("sequence")
        if raw_seq is None:
            continue

        try:
            seq = int(raw_seq)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            violations.append(
                InvariantViolation(
                    package_name="session.events",
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
                        package_name="session.events",
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
                        package_name="session.events",
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


def install_core_invariants(registry: RuntimeInvariantRegistry | None = None) -> None:
    """Install standard companion runtime invariant checks into the given registry."""
    target_registry = registry or default_invariant_registry
    target_registry.register("session.events", "session_event_pairing", check_session_event_pairing)
    target_registry.register("session.events", "step_enclosure", check_step_enclosure)
    target_registry.register("session.events", "sequence_continuity", check_sequence_continuity)
    target_registry.register("agent.lifecycle", "agent_state_transition", check_agent_state_transition)
    target_registry.register("toolkits.todo", "todo_structure_integrity", check_todo_structure_integrity)

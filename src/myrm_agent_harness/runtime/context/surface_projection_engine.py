"""Immutable Event Log SSOT and Surface Projection Engine.

Implements pure-function message derivation, surface folding with atomic replace,
and arXiv:2608.24569 constraint preservation gate against handoff weakening.
Strict 0 Any, immutable frozen structures, and thread-safe operations.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping, Sequence

from .surface_projection_types import (
    HandoffConstraints,
    MessageRole,
    ProjectedMessage,
    SessionEvent,
    SessionEventType,
    SurfaceNode,
    SurfaceOp,
    SurfaceOpType,
    SurfaceProjectionAudit,
)


def derive_messages(surface_nodes: Sequence[SurfaceNode]) -> tuple[ProjectedMessage, ...]:
    """Pure deterministic function deriving model-visible messages from surface nodes.

    Guarantees zero side-effects and returns an immutable tuple of frozen messages.
    """
    return tuple(node.message for node in surface_nodes)


class HandoffConstraintPreservationGate:
    """Gatekeeper enforcing non-weakened constraints across handoffs and compactions (arXiv:2608.24569)."""

    @staticmethod
    def render_constraint_block(constraints: HandoffConstraints) -> str:
        """Render structural non-negotiable XML block preserving the 4 core constraint dimensions."""
        if constraints.is_empty:
            return ""

        lines = ["<handoff_preserved_constraints>"]
        if constraints.security_boundaries:
            lines.append("  <security_boundaries>")
            for b in constraints.security_boundaries:
                lines.append(f"    <boundary>{b}</boundary>")
            lines.append("  </security_boundaries>")

        if constraints.permissions:
            lines.append("  <permissions>")
            for p in constraints.permissions:
                lines.append(f"    <permission>{p}</permission>")
            lines.append("  </permissions>")

        if constraints.required_artifacts:
            lines.append("  <required_artifacts>")
            for a in constraints.required_artifacts:
                lines.append(f"    <artifact>{a}</artifact>")
            lines.append("  </required_artifacts>")

        if constraints.prohibited_actions:
            lines.append("  <prohibited_actions>")
            for act in constraints.prohibited_actions:
                lines.append(f"    <prohibited>{act}</prohibited>")
            lines.append("  </prohibited_actions>")
        lines.append("</handoff_preserved_constraints>")
        return "\n".join(lines)

    @classmethod
    def create_constraint_node(
        cls, constraints: HandoffConstraints, seq: int
    ) -> SurfaceNode:
        """Create a dedicated immutable system surface node embedding preserved constraints."""
        content = cls.render_constraint_block(constraints)
        msg = ProjectedMessage(
            role=MessageRole.SYSTEM,
            content=content,
        )
        return SurfaceNode(
            node_id=f"node-constraint-{seq}",
            source_event_seq=seq,
            message=msg,
            tags=("handoff_preserved_constraint",),
        )

    @classmethod
    def guard_surface_nodes(
        cls, nodes: Sequence[SurfaceNode], constraints: HandoffConstraints | None
    ) -> tuple[SurfaceNode, ...]:
        """Ensure preserved constraints are firmly placed at the head of the context."""
        if constraints is None or constraints.is_empty:
            return tuple(nodes)

        # Check if already present
        has_constraint = any(
            "handoff_preserved_constraint" in node.tags for node in nodes
        )
        if has_constraint:
            return tuple(nodes)

        guard_node = cls.create_constraint_node(constraints, seq=0)
        return (guard_node, *nodes)


def fold_surface(
    events: Sequence[SessionEvent],
    initial_constraints: HandoffConstraints | None = None,
) -> tuple[tuple[SurfaceNode, ...], tuple[SurfaceOp, ...], SurfaceProjectionAudit]:
    """Fold an immutable event stream into a final surface node sequence and audit log.

    Pure deterministic folding algorithm supporting atomic range replacement.
    """
    surface_nodes: list[SurfaceNode] = []
    applied_ops: list[SurfaceOp] = []
    audit_trails: list[str] = []
    authoritative_count = 0

    for event in events:
        if event.event_type == SessionEventType.USER_MESSAGE:
            content = str(event.payload.get("content", ""))
            msg = ProjectedMessage(role=MessageRole.USER, content=content)
            node = SurfaceNode(
                node_id=f"node-user-{event.seq}",
                source_event_seq=event.seq,
                message=msg,
            )
            surface_nodes.append(node)
            authoritative_count += 1
            audit_trails.append(f"Append USER node at seq {event.seq}")

        elif event.event_type == SessionEventType.ASSISTANT_MESSAGE:
            content = str(event.payload.get("content", ""))
            reasoning = event.payload.get("reasoning_content")
            reasoning_str = str(reasoning) if reasoning is not None else None
            calls = event.payload.get("tool_calls")
            tool_calls_tuple: tuple[str, ...] = (
                calls if isinstance(calls, tuple) else ()
            )
            msg = ProjectedMessage(
                role=MessageRole.ASSISTANT,
                content=content,
                reasoning_content=reasoning_str,
                tool_calls=tool_calls_tuple,
            )
            node = SurfaceNode(
                node_id=f"node-assistant-{event.seq}",
                source_event_seq=event.seq,
                message=msg,
            )
            surface_nodes.append(node)
            authoritative_count += 1
            audit_trails.append(f"Append ASSISTANT node at seq {event.seq}")

        elif event.event_type == SessionEventType.TOOL_RESULT:
            content = str(event.payload.get("content", ""))
            call_id = str(event.payload.get("tool_call_id", ""))
            tool_name = str(event.payload.get("name", ""))
            msg = ProjectedMessage(
                role=MessageRole.TOOL,
                content=content,
                tool_call_id=call_id or None,
                name=tool_name or None,
            )
            node = SurfaceNode(
                node_id=f"node-tool-{event.seq}",
                source_event_seq=event.seq,
                message=msg,
            )
            surface_nodes.append(node)
            authoritative_count += 1
            audit_trails.append(f"Append TOOL node at seq {event.seq}")

        elif event.event_type == SessionEventType.SURFACE_REPLACE:
            start_idx = int(event.payload.get("start_index", 0))
            end_idx = int(event.payload.get("end_index", 0))
            summary_content = str(event.payload.get("summary_content", ""))
            reason = str(event.payload.get("reason", "compaction"))
            is_truncation = bool(event.payload.get("is_truncated", False))

            if 0 <= start_idx <= end_idx <= len(surface_nodes):
                replacement_msg = ProjectedMessage(
                    role=MessageRole.SYSTEM if not is_truncation else MessageRole.TOOL,
                    content=summary_content,
                )
                replacement_node = SurfaceNode(
                    node_id=f"node-replace-{event.seq}",
                    source_event_seq=event.seq,
                    message=replacement_msg,
                    is_summary=not is_truncation,
                    is_truncated=is_truncation,
                    tags=("compacted_summary",) if not is_truncation else ("truncated_tool",),
                )
                op = SurfaceOp(
                    op_type=SurfaceOpType.REPLACE,
                    start_index=start_idx,
                    end_index=end_idx,
                    replacement_nodes=(replacement_node,),
                    reason=reason,
                )
                surface_nodes[start_idx:end_idx] = [replacement_node]
                applied_ops.append(op)
                audit_trails.append(
                    f"Applied REPLACE op on range [{start_idx}:{end_idx}] via seq {event.seq}"
                )
        else:
            # Telemetry or chunk events are non-authoritative
            audit_trails.append(f"Skipped non-message event {event.event_type.value} at seq {event.seq}")

    final_nodes = HandoffConstraintPreservationGate.guard_surface_nodes(
        surface_nodes, initial_constraints
    )

    audit = SurfaceProjectionAudit(
        total_events=len(events),
        authoritative_events_count=authoritative_count,
        applied_ops_count=len(applied_ops),
        final_node_count=len(final_nodes),
        has_preserved_constraints=bool(initial_constraints and not initial_constraints.is_empty),
        audit_trail=tuple(audit_trails),
    )
    return final_nodes, tuple(applied_ops), audit


class ImmutableEventLog:
    """Thread-safe append-only immutable event log serving as the SSOT."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: list[SessionEvent] = []
        self._seq_counter: int = 0

    def append(
        self,
        event_type: SessionEventType,
        payload: Mapping[str, str | int | float | bool | tuple[str, ...]],
        event_id: str = "",
    ) -> SessionEvent:
        """Atomically append a new immutable event."""
        with self._lock:
            self._seq_counter += 1
            ev = SessionEvent(
                seq=self._seq_counter,
                event_type=event_type,
                timestamp=time.time(),
                payload=dict(payload),
                event_id=event_id or f"evt-{self._seq_counter}",
            )
            self._events.append(ev)
            return ev

    def get_snapshot(self) -> tuple[SessionEvent, ...]:
        """Return an immutable snapshot of all events."""
        with self._lock:
            return tuple(self._events)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


class SurfaceProjectionEngine:
    """Façade orchestrating immutable event logging, cached surface projection, and constraint preservation."""

    def __init__(self, constraints: HandoffConstraints | None = None) -> None:
        self._lock = threading.RLock()
        self._event_log = ImmutableEventLog()
        self._constraints = constraints
        self._cached_nodes: tuple[SurfaceNode, ...] | None = None
        self._cached_messages: tuple[ProjectedMessage, ...] | None = None
        self._cached_audit: SurfaceProjectionAudit | None = None

    def record_event(
        self,
        event_type: SessionEventType,
        payload: Mapping[str, str | int | float | bool | tuple[str, ...]],
        event_id: str = "",
    ) -> SessionEvent:
        """Record an event into the SSOT and invalidate surface cache."""
        with self._lock:
            ev = self._event_log.append(event_type, payload, event_id)
            self._invalidate_cache()
            return ev

    def compact_range(
        self, start_index: int, end_index: int, summary: str, reason: str = "compaction"
    ) -> SessionEvent:
        """Apply atomic compaction without altering history by logging a SURFACE_REPLACE event."""
        payload: dict[str, str | int | float | bool | tuple[str, ...]] = {
            "start_index": start_index,
            "end_index": end_index,
            "summary_content": summary,
            "reason": reason,
            "is_truncated": False,
        }
        return self.record_event(SessionEventType.SURFACE_REPLACE, payload)

    def prune_tool_result(
        self, node_index: int, truncated_content: str, reason: str = "tool_output_pruning"
    ) -> SessionEvent:
        """Apply tool result pruning replacement without destroying underlying raw logs."""
        payload: dict[str, str | int | float | bool | tuple[str, ...]] = {
            "start_index": node_index,
            "end_index": node_index + 1,
            "summary_content": truncated_content,
            "reason": reason,
            "is_truncated": True,
        }
        return self.record_event(SessionEventType.SURFACE_REPLACE, payload)

    def update_constraints(self, constraints: HandoffConstraints) -> None:
        """Update preserved constraints and invalidate cache."""
        with self._lock:
            self._constraints = constraints
            self._invalidate_cache()

    def get_surface_nodes(self) -> tuple[SurfaceNode, ...]:
        """Get cached or freshly folded surface nodes."""
        with self._lock:
            if self._cached_nodes is None:
                self._recompute_projection()
            assert self._cached_nodes is not None
            return self._cached_nodes

    def derive_model_context(self) -> tuple[ProjectedMessage, ...]:
        """Derive cached model-visible messages for LLM context injection."""
        with self._lock:
            if self._cached_messages is None:
                nodes = self.get_surface_nodes()
                self._cached_messages = derive_messages(nodes)
            return self._cached_messages

    def get_audit(self) -> SurfaceProjectionAudit:
        """Get the audit report from the latest projection fold."""
        with self._lock:
            if self._cached_audit is None:
                self._recompute_projection()
            assert self._cached_audit is not None
            return self._cached_audit

    def _invalidate_cache(self) -> None:
        self._cached_nodes = None
        self._cached_messages = None
        self._cached_audit = None

    def _recompute_projection(self) -> None:
        events = self._event_log.get_snapshot()
        nodes, _, audit = fold_surface(events, self._constraints)
        self._cached_nodes = nodes
        self._cached_audit = audit

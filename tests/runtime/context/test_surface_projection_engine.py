"""Unit tests for Immutable Event Log SSOT and Surface Projection Engine.

Validates pure deriveMessages, foldSurface with atomic replace,
and arXiv:2608.24569 Handoff Constraint Preservation Gate.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import FrozenInstanceError

import pytest

from myrm_agent_harness.runtime.context.surface_projection_engine import (
    ImmutableEventLog,
    SurfaceProjectionEngine,
    derive_messages,
    fold_surface,
)
from myrm_agent_harness.runtime.context.surface_projection_types import (
    HandoffConstraints,
    MessageRole,
    ProjectedMessage,
    SessionEventType,
    SurfaceNode,
)


def test_pure_derive_messages_and_immutability() -> None:
    """Verify derive_messages is deterministic, pure, and returns frozen objects."""
    msg1 = ProjectedMessage(role=MessageRole.USER, content="Hello")
    msg2 = ProjectedMessage(role=MessageRole.ASSISTANT, content="Hi there!")
    node1 = SurfaceNode(node_id="n1", source_event_seq=1, message=msg1)
    node2 = SurfaceNode(node_id="n2", source_event_seq=2, message=msg2)

    derived = derive_messages([node1, node2])
    assert len(derived) == 2
    assert derived[0] == msg1
    assert derived[1] == msg2

    # Immutability verification
    with pytest.raises(FrozenInstanceError):
        msg1.content = "Tampered"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        node1.node_id = "Tampered"  # type: ignore[misc]


def test_event_log_ssot_and_filtering() -> None:
    """Verify that only authoritative message events produce surface nodes."""
    log = ImmutableEventLog()
    log.append(SessionEventType.TURN_START, {"turn": 1})
    log.append(SessionEventType.STEP_START, {"step": 1})
    log.append(SessionEventType.USER_MESSAGE, {"content": "User request 1"})
    log.append(SessionEventType.ASSISTANT_CHUNK, {"chunk": "Let "})
    log.append(SessionEventType.ASSISTANT_CHUNK, {"chunk": "me think"})
    log.append(
        SessionEventType.ASSISTANT_MESSAGE,
        {"content": "I will execute a tool", "reasoning_content": "Chain-of-thought hypothesis"},
    )
    log.append(SessionEventType.TOOL_CALL, {"tool": "search"})
    log.append(
        SessionEventType.TOOL_RESULT,
        {"content": "Result 42", "tool_call_id": "call-1", "name": "search"},
    )
    log.append(SessionEventType.HEARTBEAT, {"status": "alive"})

    assert len(log) == 9
    events = log.get_snapshot()

    nodes, ops, audit = fold_surface(events)
    assert len(ops) == 0
    assert audit.total_events == 9
    assert audit.authoritative_events_count == 3
    assert audit.final_node_count == 3

    messages = derive_messages(nodes)
    assert len(messages) == 3
    assert messages[0].role == MessageRole.USER
    assert messages[0].content == "User request 1"
    assert messages[1].role == MessageRole.ASSISTANT
    assert messages[1].content == "I will execute a tool"
    assert messages[1].reasoning_content == "Chain-of-thought hypothesis"
    assert messages[2].role == MessageRole.TOOL
    assert messages[2].content == "Result 42"
    assert messages[2].tool_call_id == "call-1"
    assert messages[2].name == "search"


def test_atomic_surface_compaction_replace() -> None:
    """Verify surface range replacement preserves underlying immutable log while shrinking context."""
    engine = SurfaceProjectionEngine()
    engine.record_event(SessionEventType.USER_MESSAGE, {"content": "Task part 1"})
    engine.record_event(SessionEventType.ASSISTANT_MESSAGE, {"content": "Done part 1"})
    engine.record_event(SessionEventType.USER_MESSAGE, {"content": "Task part 2"})
    engine.record_event(SessionEventType.ASSISTANT_MESSAGE, {"content": "Done part 2"})

    # Before compaction: 4 nodes
    assert len(engine.get_surface_nodes()) == 4

    # Compact range [0:4] into 1 summary node
    replace_ev = engine.compact_range(
        start_index=0,
        end_index=4,
        summary="Summary of Part 1 and Part 2 completed successfully.",
        reason="token_budget_compaction",
    )
    assert replace_ev.event_type == SessionEventType.SURFACE_REPLACE

    # After compaction: 1 summary node
    compacted_nodes = engine.get_surface_nodes()
    assert len(compacted_nodes) == 1
    assert compacted_nodes[0].is_summary is True
    assert "compacted_summary" in compacted_nodes[0].tags
    assert (
        compacted_nodes[0].message.content
        == "Summary of Part 1 and Part 2 completed successfully."
    )

    # Append new turn
    engine.record_event(SessionEventType.USER_MESSAGE, {"content": "Task part 3"})
    updated_nodes = engine.get_surface_nodes()
    assert len(updated_nodes) == 2
    assert updated_nodes[1].message.content == "Task part 3"

    # Underlying SSOT has all raw events intact (4 original + 1 replace + 1 new = 6)
    assert len(engine._event_log.get_snapshot()) == 6


def test_tool_result_pruning() -> None:
    """Verify tool output pruning truncates model-visible text without destroying raw log."""
    engine = SurfaceProjectionEngine()
    engine.record_event(SessionEventType.USER_MESSAGE, {"content": "Run diagnostics"})
    huge_output = "Line " * 5000
    engine.record_event(
        SessionEventType.TOOL_RESULT,
        {"content": huge_output, "tool_call_id": "call-diag", "name": "run_diagnostics"},
    )

    nodes_before = engine.get_surface_nodes()
    assert len(nodes_before) == 2
    assert len(nodes_before[1].message.content) > 10000

    # Prune node 1
    engine.prune_tool_result(
        node_index=1,
        truncated_content="[Output truncated: Line x 5000 lines...]",
        reason="giant_tool_output",
    )

    nodes_after = engine.get_surface_nodes()
    assert len(nodes_after) == 2
    assert nodes_after[1].is_truncated is True
    assert "truncated_tool" in nodes_after[1].tags
    assert nodes_after[1].message.content == "[Output truncated: Line x 5000 lines...]"

    # Underlying log still contains original huge output
    events = engine._event_log.get_snapshot()
    assert events[1].payload.get("content") == huge_output


def test_arxiv_2608_24569_handoff_constraint_preservation_gate() -> None:
    """Verify arXiv:2608.24569 HandoffConstraintPreservationGate prevents rule weakening."""
    constraints = HandoffConstraints(
        security_boundaries=("No write outside /workspace", "No plain-text secrets in prompt"),
        permissions=("read:all", "execute:sandboxed"),
        required_artifacts=("FINAL_REPORT.json", "diff.patch"),
        prohibited_actions=("rm -rf /", "git push --force"),
    )

    engine = SurfaceProjectionEngine(constraints=constraints)
    engine.record_event(SessionEventType.USER_MESSAGE, {"content": "Initialize workspace"})
    engine.record_event(SessionEventType.ASSISTANT_MESSAGE, {"content": "Workspace initialized"})

    # Even after compacting all normal messages
    engine.compact_range(
        start_index=0,
        end_index=2,
        summary="Workspace was initialized.",
    )

    nodes = engine.get_surface_nodes()
    # Guard node must be present at index 0
    assert len(nodes) == 2  # Guard node + 1 summary node
    assert nodes[0].message.role == MessageRole.SYSTEM
    assert "handoff_preserved_constraint" in nodes[0].tags

    guard_text = nodes[0].message.content
    assert "<handoff_preserved_constraints>" in guard_text
    assert "<boundary>No write outside /workspace</boundary>" in guard_text
    assert "<permission>read:all</permission>" in guard_text
    assert "<artifact>FINAL_REPORT.json</artifact>" in guard_text
    assert "<prohibited>rm -rf /</prohibited>" in guard_text

    audit = engine.get_audit()
    assert audit.has_preserved_constraints is True


def test_surface_projection_engine_concurrency_and_cache() -> None:
    """Verify thread-safety and cache invalidation under concurrent event writes."""
    engine = SurfaceProjectionEngine()

    def worker(worker_id: int) -> None:
        for i in range(10):
            engine.record_event(
                SessionEventType.USER_MESSAGE,
                {"content": f"Worker {worker_id} message {i}"},
            )
            # Query surface concurrently to test cache read/invalidation under lock
            context = engine.derive_model_context()
            assert len(context) > 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, w) for w in range(4)]
        for fut in concurrent.futures.as_completed(futures):
            fut.result()

    final_context = engine.derive_model_context()
    assert len(final_context) == 40
    audit = engine.get_audit()
    assert audit.final_node_count == 40

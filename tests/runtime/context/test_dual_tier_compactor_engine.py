"""Unit tests for Dual-Tier Micro/Full Adaptive Compactor, SteerQueue,
and ToolLoopTracker Watchdog.
"""

from __future__ import annotations

import concurrent.futures

from myrm_agent_harness.runtime.context.dual_tier_compactor_engine import (
    DualTierAdaptiveCompactor,
    SteerQueue,
)
from myrm_agent_harness.runtime.context.dual_tier_compactor_types import (
    CompactorTierKind,
)
from myrm_agent_harness.runtime.context.surface_projection_types import (
    MessageRole,
    ProjectedMessage,
)
from myrm_agent_harness.runtime.context.tool_loop_tracker import ToolLoopTracker


def test_micro_compact_rule_based_folding() -> None:
    """Verify Micro-compact folds oversized historical tool outputs outside the preserved recent window."""
    huge_html = "<div>Detailed webpage content with thousands of DOM nodes</div>" * 40

    messages = [
        ProjectedMessage(role=MessageRole.USER, content="Step 1: Fetch documentation"),
        ProjectedMessage(
            role=MessageRole.ASSISTANT,
            content="Fetching docs",
            tool_calls=('{"name": "web_fetch", "arguments": {"url": "https://example.com/docs"}}',),
        ),
        ProjectedMessage(
            role=MessageRole.TOOL,
            content=huge_html,
            tool_call_id="call-fetch-1",
            name="web_fetch",
        ),
        ProjectedMessage(role=MessageRole.USER, content="Step 2: Read additional notes"),
        ProjectedMessage(role=MessageRole.ASSISTANT, content="Done reading notes"),
        ProjectedMessage(role=MessageRole.USER, content="Step 3: Analyze extracted data"),
        ProjectedMessage(
            role=MessageRole.ASSISTANT,
            content="Recent action",
            tool_calls=('{"name": "grep", "arguments": {"pattern": "API"}}',),
        ),
        ProjectedMessage(
            role=MessageRole.TOOL,
            content="Recent small tool output",
            tool_call_id="call-grep-1",
            name="grep",
        ),
    ]

    # Context window set so that huge_html triggers micro-compact but stays under full-compact
    compacted_msgs, decision = DualTierAdaptiveCompactor.evaluate_and_compact(
        messages=messages,
        context_window=1000,
        micro_threshold_ratio=0.50,
        full_threshold_ratio=0.90,
        preserve_recent_turns=2,
        min_fold_chars=200,
    )

    assert decision.tier == CompactorTierKind.MICRO
    assert decision.triggered is True
    assert decision.saved_tokens > 0
    assert len(decision.folded_items) == 1

    # Verify that message 2 (the historical huge tool result) was folded
    folded_tool_msg = compacted_msgs[2]
    assert "[Tool Output Folded (web_fetch):" in folded_tool_msg.content
    assert "omitted to preserve context window" in folded_tool_msg.content

    # Verify that the recent tool output (message 7) was preserved intact
    recent_tool_msg = compacted_msgs[7]
    assert recent_tool_msg.content == "Recent small tool output"


def test_escalation_to_full_compact() -> None:
    """Verify adaptive escalation to Full-compact when Micro-compact cannot reduce tokens below threshold."""
    # Construct a message sequence with huge text across user/assistant conversations
    messages = [
        ProjectedMessage(role=MessageRole.USER, content="Analyze architecture: " + ("spec line " * 200)),
        ProjectedMessage(role=MessageRole.ASSISTANT, content="Initial response: " + ("analysis line " * 200)),
        ProjectedMessage(role=MessageRole.USER, content="Phase 2: " + ("requirement line " * 200)),
        ProjectedMessage(role=MessageRole.ASSISTANT, content="Phase 2 response: " + ("architecture line " * 200)),
        ProjectedMessage(role=MessageRole.USER, content="Current final question"),
    ]

    compacted_msgs, decision = DualTierAdaptiveCompactor.evaluate_and_compact(
        messages=messages,
        context_window=500,  # Tight window forcing Full-compact
        micro_threshold_ratio=0.50,
        full_threshold_ratio=0.70,
    )

    assert decision.tier == CompactorTierKind.FULL
    assert decision.triggered is True
    assert decision.saved_tokens > 0
    assert "<compaction_context>" in compacted_msgs[0].content


def test_steer_queue_mid_task_injection() -> None:
    """Verify SteerQueue safely enqueues, drains, and renders XML instruction blocks."""
    queue = SteerQueue()
    assert len(queue.peek()) == 0

    s1 = queue.enqueue("Stop querying 2024 data, switch to 2026 reports immediately", priority=1)
    s2 = queue.enqueue("Make sure to format results in Markdown table", priority=2)

    assert len(queue.peek()) == 2
    rendered = SteerQueue.render_steer_prompt_block(queue.peek())
    assert "<mid_task_user_steering>" in rendered
    assert f"<instruction id='{s1.instruction_id}' priority='1'>" in rendered
    assert f"<instruction id='{s2.instruction_id}' priority='2'>" in rendered

    # Drain atomically
    drained = queue.drain()
    assert len(drained) == 2
    assert len(queue.peek()) == 0


def test_tool_loop_tracker_direct_repetition() -> None:
    """Verify ToolLoopTracker trips when a tool is called with identical arguments 3 times consecutively."""
    tracker = ToolLoopTracker(max_consecutive_identical=3)

    state1 = tracker.record_call("read_file", {"path": "src/main.py"})
    assert state1.is_tripped is False

    state2 = tracker.record_call("read_file", {"path": "src/main.py"})
    assert state2.is_tripped is False

    state3 = tracker.record_call("read_file", {"path": "src/main.py"})
    assert state3.is_tripped is True
    assert "Identical tool 'read_file' called 3 times in a row" in state3.trip_reason
    assert "<tool_loop_circuit_breaker tool='read_file'" in state3.remediation_directive


def test_tool_loop_tracker_ping_pong_oscillation() -> None:
    """Verify ToolLoopTracker trips when an alternating ping-pong oscillation is detected."""
    tracker = ToolLoopTracker(max_oscillation_cycles=2)

    # Sequence: ToolA -> ToolB -> ToolA -> ToolB (period 2, 2 cycles)
    tracker.record_call("list_dir", {"path": "src/"})
    tracker.record_call("view_file", {"path": "src/index.ts"})
    tracker.record_call("list_dir", {"path": "src/"})
    state = tracker.record_call("view_file", {"path": "src/index.ts"})

    assert state.is_tripped is True
    assert "Alternating tool oscillation of period 2 detected" in state.trip_reason
    assert "<tool_loop_circuit_breaker tool='view_file' error_type='oscillation'>" in state.remediation_directive

    # Reset
    tracker.reset()
    assert tracker.is_tripped is False
    assert tracker.get_state().is_tripped is False


def test_tool_loop_tracker_consecutive_errors_and_thread_safety() -> None:
    """Verify persistent error tripping and multi-threaded concurrency safety."""
    tracker = ToolLoopTracker(max_consecutive_errors=3)

    tracker.record_call("api_call", {"endpoint": "/v1/data/1"}, is_error=True)
    tracker.record_call("api_call", {"endpoint": "/v1/data/2"}, is_error=True)
    state = tracker.record_call("api_call", {"endpoint": "/v1/data/3"}, is_error=True)

    assert state.is_tripped is True
    assert "failed 3 consecutive times" in state.trip_reason

    # Thread safety test
    queue = SteerQueue()

    def worker(worker_id: int) -> None:
        for i in range(10):
            queue.enqueue(f"Worker {worker_id} steering command {i}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, w) for w in range(4)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert len(queue.drain()) == 40

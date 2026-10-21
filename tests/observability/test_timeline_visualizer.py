"""Unit tests for TaskExecutionTimelineCollector and timeline visualizer models."""

import time
import pytest

from myrm_agent_harness.observability.timeline_visualizer import (
    TaskExecutionTimelineCollector,
    TimelineIOMetrics,
    TimelineNodeStatus,
    TimelineNodeType,
    TimelineStepNode,
)


def test_start_and_complete_step() -> None:
    collector = TaskExecutionTimelineCollector(task_id="task_test_001")

    node_id = collector.start_step(
        step_name="ReadFileStep",
        node_type="tool_invocation",
        input_payload={"path": "/workspace/main.py"},
    )

    node = collector.get_node(node_id)
    assert node is not None
    assert node.step_name == "ReadFileStep"
    assert node.status == "running"
    assert node.duration_ms is None
    assert node.input_payload == {"path": "/workspace/main.py"}

    time.sleep(0.01)  # small delta to guarantee duration > 0

    metrics = TimelineIOMetrics(
        input_chars=30,
        output_chars=500,
        prompt_tokens=15,
        completion_tokens=120,
        cache_hit=True,
    )
    collector.complete_step(
        node_id=node_id,
        output_payload={"content": "def main(): pass"},
        metrics=metrics,
    )

    node_after = collector.get_node(node_id)
    assert node_after is not None
    assert node_after.status == "completed"
    assert node_after.end_time_ms is not None
    assert node_after.duration_ms is not None and node_after.duration_ms > 0
    assert node_after.output_payload == {"content": "def main(): pass"}
    assert node_after.metrics.cache_hit is True
    assert node_after.metrics.prompt_tokens == 15


def test_fail_and_interrupt_step() -> None:
    collector = TaskExecutionTimelineCollector(task_id="task_test_002")

    fail_id = collector.start_step(step_name="NetworkFetch", node_type="mcp_call")
    collector.fail_step(fail_id, error_message="Connection timeout")

    fail_node = collector.get_node(fail_id)
    assert fail_node is not None
    assert fail_node.status == "failed"
    assert fail_node.error_message == "Connection timeout"

    interrupt_id = collector.start_step(step_name="LongComputation", node_type="agent_thought")
    collector.interrupt_step(interrupt_id, reason="user_cancelled")

    interrupt_node = collector.get_node(interrupt_id)
    assert interrupt_node is not None
    assert interrupt_node.status == "interrupted"
    assert "user_cancelled" in (interrupt_node.error_message or "")


def test_timeline_tree_and_waterfall_ordering() -> None:
    collector = TaskExecutionTimelineCollector(task_id="task_test_003")

    root_id = collector.start_step(step_name="PlanTask", node_type="agent_thought")
    child1_id = collector.start_step(
        step_name="RunLint",
        node_type="tool_invocation",
        parent_id=root_id,
    )
    child2_id = collector.start_step(
        step_name="RunTest",
        node_type="tool_invocation",
        parent_id=root_id,
    )
    independent_id = collector.start_step(step_name="TelemetryCheck", node_type="system_io")

    tree = collector.get_timeline_tree()
    assert len(tree) == 2  # root_id and independent_id

    plan_root = next(n for n in tree if n.node_id == root_id)
    assert len(plan_root.children) == 2
    assert {c.node_id for c in plan_root.children} == {child1_id, child2_id}

    waterfall = collector.get_waterfall_nodes()
    assert len(waterfall) == 4
    for i in range(len(waterfall) - 1):
        assert waterfall[i].start_time_ms <= waterfall[i + 1].start_time_ms


def test_summary_stats() -> None:
    collector = TaskExecutionTimelineCollector(task_id="task_test_004")

    s1 = collector.start_step("Step1", node_type="tool_invocation")
    collector.complete_step(s1, metrics=TimelineIOMetrics(prompt_tokens=10, completion_tokens=20))

    s2 = collector.start_step("Step2", node_type="tool_invocation")
    collector.fail_step(s2, "Disk error")

    s3 = collector.start_step("Step3", node_type="agent_thought")
    collector.interrupt_step(s3)

    collector.start_step("Step4", node_type="tool_invocation")  # running

    stats = collector.get_summary_stats()
    assert stats["total_steps"] == 4
    assert stats["completed_steps"] == 1
    assert stats["failed_steps"] == 1
    assert stats["interrupted_steps"] == 1
    assert stats["running_steps"] == 1
    assert stats["total_tokens"] == 30

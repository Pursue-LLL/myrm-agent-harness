"""[INPUT]
- TimelineNodeType, TimelineNodeStatus, TimelineIOMetrics, TimelineStepNode from .timeline_models

[OUTPUT]
- TaskExecutionTimelineCollector: Thread-safe in-memory execution inspector and waterfall builder

[POS]
Harness framework layer collector recording live task steps, skill calls, and execution timelines.
"""

from __future__ import annotations

import threading
import uuid

from .timeline_models import (
    TimelineIOMetrics,
    TimelineNodeType,
    TimelineStepNode,
)


class TaskExecutionTimelineCollector:
    """Thread-safe collector for capturing step lifecycles and constructing execution waterfall trees."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self._lock = threading.Lock()
        self._nodes: dict[str, TimelineStepNode] = {}
        self._counter: int = 0

    def start_step(
        self,
        step_name: str,
        node_type: TimelineNodeType = "tool_invocation",
        parent_id: str | None = None,
        input_payload: dict[str, str] | None = None,
        node_id: str | None = None,
    ) -> str:
        with self._lock:
            self._counter += 1
            nid = node_id or f"node_{uuid.uuid4().hex[:10]}"
            node = TimelineStepNode(
                node_id=nid,
                step_name=step_name,
                parent_id=parent_id,
                step_index=self._counter,
                node_type=node_type,
                status="running",
                input_payload=input_payload,
            )
            self._nodes[nid] = node
            return nid

    def complete_step(
        self,
        node_id: str,
        output_payload: dict[str, str] | None = None,
        metrics: TimelineIOMetrics | None = None,
    ) -> None:
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].mark_completed(output_payload=output_payload, metrics=metrics)

    def fail_step(self, node_id: str, error_message: str) -> None:
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].mark_failed(error_message=error_message)

    def interrupt_step(self, node_id: str, reason: str = "user_barge_in") -> None:
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].mark_interrupted(reason=reason)

    def get_node(self, node_id: str) -> TimelineStepNode | None:
        with self._lock:
            return self._nodes.get(node_id)

    def get_waterfall_nodes(self) -> list[TimelineStepNode]:
        """Returns flattened list of nodes sorted chronologically by start_time_ms."""
        with self._lock:
            return sorted(self._nodes.values(), key=lambda n: n.start_time_ms)

    def get_timeline_tree(self) -> list[TimelineStepNode]:
        """Constructs and returns hierarchical tree topology of execution steps."""
        with self._lock:
            nodes_copy = {nid: self._clone_node(n) for nid, n in self._nodes.items()}

            roots: list[TimelineStepNode] = []
            for node in nodes_copy.values():
                if node.parent_id and node.parent_id in nodes_copy:
                    nodes_copy[node.parent_id].children.append(node)
                else:
                    roots.append(node)

            return sorted(roots, key=lambda n: n.start_time_ms)

    def get_summary_stats(self) -> dict[str, int | float]:
        with self._lock:
            total_nodes = len(self._nodes)
            completed_count = sum(1 for n in self._nodes.values() if n.status == "completed")
            failed_count = sum(1 for n in self._nodes.values() if n.status == "failed")
            running_count = sum(1 for n in self._nodes.values() if n.status == "running")
            interrupted_count = sum(1 for n in self._nodes.values() if n.status == "interrupted")

            total_duration_ms = sum(n.duration_ms or 0.0 for n in self._nodes.values())
            total_tokens = sum(
                (n.metrics.prompt_tokens or 0) + (n.metrics.completion_tokens or 0)
                for n in self._nodes.values()
            )

            return {
                "total_steps": total_nodes,
                "completed_steps": completed_count,
                "failed_steps": failed_count,
                "running_steps": running_count,
                "interrupted_steps": interrupted_count,
                "total_duration_ms": round(total_duration_ms, 2),
                "total_tokens": total_tokens,
            }

    @staticmethod
    def _clone_node(node: TimelineStepNode) -> TimelineStepNode:
        return TimelineStepNode(
            node_id=node.node_id,
            step_name=node.step_name,
            parent_id=node.parent_id,
            step_index=node.step_index,
            node_type=node.node_type,
            status=node.status,
            start_time_ms=node.start_time_ms,
            end_time_ms=node.end_time_ms,
            duration_ms=node.duration_ms,
            input_payload=dict(node.input_payload) if node.input_payload else None,
            output_payload=dict(node.output_payload) if node.output_payload else None,
            metrics=TimelineIOMetrics(
                input_chars=node.metrics.input_chars,
                output_chars=node.metrics.output_chars,
                prompt_tokens=node.metrics.prompt_tokens,
                completion_tokens=node.metrics.completion_tokens,
                cache_hit=node.metrics.cache_hit,
            ),
            error_message=node.error_message,
            children=[],
        )

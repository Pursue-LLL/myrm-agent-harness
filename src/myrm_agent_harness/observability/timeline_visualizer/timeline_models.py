"""[INPUT]
- None (pure data contract)

[OUTPUT]
- TimelineNodeType, TimelineNodeStatus, TimelineIOMetrics, TimelineStepNode

[POS]
Harness framework layer execution timeline and step tree data contracts.
Supports millisecond-precision durations, IO metrics, and hierarchical task inspection.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

TimelineNodeType = Literal[
    "agent_thought",
    "skill_call",
    "tool_invocation",
    "mcp_call",
    "checkpoint",
    "system_io",
]

TimelineNodeStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "interrupted",
]


@dataclass(slots=True)
class TimelineIOMetrics:
    input_chars: int = 0
    output_chars: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cache_hit: bool = False


@dataclass(slots=True)
class TimelineStepNode:
    node_id: str
    step_name: str
    parent_id: str | None = None
    step_index: int = 0
    node_type: TimelineNodeType = "tool_invocation"
    status: TimelineNodeStatus = "running"
    start_time_ms: float = field(default_factory=lambda: time.time() * 1000.0)
    end_time_ms: float | None = None
    duration_ms: float | None = None
    input_payload: dict[str, str] | None = None
    output_payload: dict[str, str] | None = None
    metrics: TimelineIOMetrics = field(default_factory=TimelineIOMetrics)
    error_message: str | None = None
    children: list[TimelineStepNode] = field(default_factory=list)

    def mark_completed(
        self,
        output_payload: dict[str, str] | None = None,
        metrics: TimelineIOMetrics | None = None,
    ) -> None:
        self.status = "completed"
        self.end_time_ms = time.time() * 1000.0
        self.duration_ms = max(0.0, self.end_time_ms - self.start_time_ms)
        if output_payload is not None:
            self.output_payload = output_payload
        if metrics is not None:
            self.metrics = metrics

    def mark_failed(self, error_message: str) -> None:
        self.status = "failed"
        self.end_time_ms = time.time() * 1000.0
        self.duration_ms = max(0.0, self.end_time_ms - self.start_time_ms)
        self.error_message = error_message

    def mark_interrupted(self, reason: str = "user_barge_in") -> None:
        self.status = "interrupted"
        self.end_time_ms = time.time() * 1000.0
        self.duration_ms = max(0.0, self.end_time_ms - self.start_time_ms)
        self.error_message = f"Execution interrupted: {reason}"

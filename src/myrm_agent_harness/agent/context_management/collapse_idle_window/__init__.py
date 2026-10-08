"""Collapse-idle-before-cut stream windowing subsystem protecting tail execution fidelity.

[INPUT]
- None (Public package entry point).

[OUTPUT]
- CollapseWindowConfig: Parameter settings for stream bounding, pruning, and window size.
- CollapseWindowCutEngine: Pipeline engine enforcing collapse-before-cut causal sequencing.
- CollapseWindowReceipt: Verifiable audit receipt summarizing step reduction metrics.
- HeadlongCollapseIdleBeforeCutSuite: Unified facade suite for stream collapsing and window cutting.
- IdleStreamCollapser: Sub-engine collapsing consecutive idle/error runs and pruning noise.
- StepType: Event step classification enum.
- StreamStepItem: Stream event model.
- collapse_then_cut_stream: Functional shortcut executing collapse-before-cut pipeline.
- format_time_duration: Format duration in seconds into human-readable elapsed time string.
- make_stream_step: Convenience constructor for immutable stream step items.

[POS]
Package entry point for Headlong collapse-idle-before-cut stream windowing.
"""

from __future__ import annotations

from .collapse_idle_types import (
    CollapseWindowConfig,
    CollapseWindowReceipt,
    StepType,
    StreamStepItem,
)
from .collapse_window_cut_engine import CollapseWindowCutEngine
from .headlong_collapse_idle_suite import (
    HeadlongCollapseIdleBeforeCutSuite,
    collapse_then_cut_stream,
    make_stream_step,
)
from .idle_stream_collapser import (
    IdleStreamCollapser,
    format_time_duration,
)

__all__ = [
    "CollapseWindowConfig",
    "CollapseWindowCutEngine",
    "CollapseWindowReceipt",
    "HeadlongCollapseIdleBeforeCutSuite",
    "IdleStreamCollapser",
    "StepType",
    "StreamStepItem",
    "collapse_then_cut_stream",
    "format_time_duration",
    "make_stream_step",
]

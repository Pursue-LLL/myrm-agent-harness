# [INPUT]: CollapseWindowConfig, CollapseWindowReceipt, StepType, StreamStepItem
# [OUTPUT]: HeadlongCollapseIdleBeforeCutSuite, collapse_then_cut_stream, make_stream_step
# [POS]: agent/context_management/collapse_idle_window/headlong_collapse_idle_suite.py

"""Comprehensive facade suite for Headlong collapse-idle-before-cut stream windowing.

[INPUT]
- CollapseWindowConfig: Parameter settings for stream bounding, pruning, and window size.
- CollapseWindowReceipt: Verifiable audit receipt summarizing step reduction metrics.
- StepType: Event classification enum.
- StreamStepItem: Stream event model.

[OUTPUT]
- HeadlongCollapseIdleBeforeCutSuite: Unified facade suite for stream collapsing and window cutting.
- collapse_then_cut_stream: Functional shortcut executing collapse-before-cut pipeline.
- make_stream_step: Convenience constructor for immutable stream step items.

[POS]
End-to-end facade suite for collapse-idle-before-cut stream windowing.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence

from .collapse_idle_types import (
    CollapseWindowConfig,
    CollapseWindowReceipt,
    StepType,
    StreamStepItem,
)
from .collapse_window_cut_engine import CollapseWindowCutEngine


def make_stream_step(
    step_id: str,
    run_id: str,
    step_type: StepType,
    content: str,
    *,
    timestamp: float | None = None,
    return_code: int | None = None,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> StreamStepItem:
    """Convenience constructor creating a strongly typed StreamStepItem."""
    ts = timestamp if timestamp is not None else time.time()
    return StreamStepItem(
        step_id=step_id,
        run_id=run_id,
        step_type=step_type,
        content=content,
        timestamp=ts,
        return_code=return_code,
        collapsed_count=1,
        duration_seconds=0.0,
        first_timestamp=ts,
        last_timestamp=ts,
        metadata=dict(metadata) if metadata else {},
    )


def collapse_then_cut_stream(
    steps: Sequence[StreamStepItem],
    *,
    target_window_size: int = 20,
    raw_tail_bound: int = 500,
) -> tuple[tuple[StreamStepItem, ...], CollapseWindowReceipt]:
    """Execute the canonical collapse-before-cut transformation on an execution stream."""
    cfg = CollapseWindowConfig(
        target_window_size=target_window_size,
        raw_tail_bound=raw_tail_bound,
    )
    engine = CollapseWindowCutEngine(cfg)
    return engine.process_stream(steps)


class HeadlongCollapseIdleBeforeCutSuite:
    """Unified suite orchestrating stream noise pruning, idle collapsing, and post-collapse window cutting."""

    def __init__(self, config: CollapseWindowConfig | None = None) -> None:
        self._config = config if config is not None else CollapseWindowConfig()
        self._engine = CollapseWindowCutEngine(self._config)

    @property
    def config(self) -> CollapseWindowConfig:
        return self._config

    def process_stream(
        self,
        steps: Sequence[StreamStepItem],
        override_config: CollapseWindowConfig | None = None,
    ) -> tuple[tuple[StreamStepItem, ...], CollapseWindowReceipt]:
        """Process stream steps through the collapse-before-cut pipeline."""
        if override_config is not None:
            engine = CollapseWindowCutEngine(override_config)
            return engine.process_stream(steps)
        return self._engine.process_stream(steps)

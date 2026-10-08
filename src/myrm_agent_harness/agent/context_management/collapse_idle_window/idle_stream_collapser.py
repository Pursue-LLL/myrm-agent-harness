# [INPUT]: CollapseWindowConfig, StepType, StreamStepItem
# [OUTPUT]: IdleStreamCollapser, format_time_duration
# [POS]: agent/context_management/collapse_idle_window/idle_stream_collapser.py

"""Stream pruning and consecutive idle/error step collapsing engine.

[INPUT]
- CollapseWindowConfig: Rules governing redundant step pruning and reasoning filtering.
- StepType: Discriminator enum identifying idle, error, action, etc.
- StreamStepItem: Canonical immutable model of a stream event step.

[OUTPUT]
- IdleStreamCollapser: Engine executing redundant pruning and consecutive run collapsing.
- format_time_duration: Format duration in seconds into human-readable elapsed time string.

[POS]
Consecutive idle run collapsing and stream noise pruning implementation.
"""

from __future__ import annotations

import math
from typing import Sequence

from .collapse_idle_types import CollapseWindowConfig, StepType, StreamStepItem


def format_time_duration(seconds: float) -> str:
    """Format duration into concise elapsed time string matching headlong design."""
    sec = max(0, int(math.floor(seconds)))
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        minutes = sec // 60
        return f"{minutes}m"
    if sec < 86400:
        hours = sec // 3600
        minutes = (sec % 3600) // 60
        return f"{hours}h{minutes}m"
    days = sec // 86400
    hours = (sec % 86400) // 3600
    return f"{days}d{hours}h"


class IdleStreamCollapser:
    """Engine executing stream noise pruning and consecutive idle/error run collapsing."""

    def __init__(self, config: CollapseWindowConfig) -> None:
        self._config = config

    def prune_redundant_stream(
        self,
        steps: Sequence[StreamStepItem],
    ) -> tuple[tuple[StreamStepItem, ...], int]:
        """Prune ephemeral reasoning, redundant idle finals, and superseded observations."""
        pruned_count = 0
        filtered: list[StreamStepItem] = []

        # 1. First pass: ephemeral reasoning filtering and idle finals tracking
        seen_idle_runs: set[str] = set()
        for step in steps:
            if self._config.filter_ephemeral_reasoning and step.step_type == StepType.REASONING:
                pruned_count += 1
                continue

            if step.step_type == StepType.IDLE:
                seen_idle_runs.add(step.run_id)
                filtered.append(step)
                continue

            if (
                self._config.prune_idle_finals
                and step.step_type == StepType.FINAL
                and step.run_id in seen_idle_runs
            ):
                # The run already recorded an idle step; the duplicated final is dropped
                pruned_count += 1
                continue

            filtered.append(step)

        # 2. Second pass: prune nearest earlier observation superseded by final in same run
        if self._config.prune_redundant_observations:
            final_run_ids: set[str] = {
                step.run_id for step in filtered if step.step_type == StepType.FINAL
            }
            if final_run_ids:
                retained: list[StreamStepItem] = []
                # Keep tracking runs where we already dropped the nearest observation before final
                dropped_nearest_obs_for_run: set[str] = set()

                # Walk backwards to find the nearest observation before the final
                for step in reversed(filtered):
                    if (
                        step.step_type == StepType.OBSERVATION
                        and step.run_id in final_run_ids
                        and step.run_id not in dropped_nearest_obs_for_run
                    ):
                        # Drop the nearest observation duplicated by the run's final
                        dropped_nearest_obs_for_run.add(step.run_id)
                        pruned_count += 1
                        continue
                    retained.append(step)

                retained.reverse()
                filtered = retained

        return tuple(filtered), pruned_count

    def collapse_consecutive_runs(
        self,
        steps: Sequence[StreamStepItem],
    ) -> tuple[tuple[StreamStepItem, ...], int]:
        """Collapse consecutive runs of idle or error steps into single synthetic lines."""
        if not steps:
            return (), 0

        collapsed: list[StreamStepItem] = []
        collapsed_steps_count = 0

        i = 0
        n = len(steps)
        while i < n:
            curr = steps[i]
            # Only idle and error steps are collapsible
            if curr.step_type not in (StepType.IDLE, StepType.ERROR):
                collapsed.append(curr)
                i += 1
                continue

            # Group consecutive steps of the exact same collapsible step_type
            group: list[StreamStepItem] = [curr]
            j = i + 1
            while j < n and steps[j].step_type == curr.step_type:
                group.append(steps[j])
                j += 1

            if len(group) == 1:
                collapsed.append(curr)
                i = j
                continue

            # Multi-step consecutive run collapsed into one synthetic step
            count = len(group)
            collapsed_steps_count += count - 1
            first_step = group[0]
            last_step = group[-1]
            first_ts = first_step.first_timestamp if first_step.first_timestamp is not None else first_step.timestamp
            last_ts = last_step.last_timestamp if last_step.last_timestamp is not None else last_step.timestamp
            duration = max(0.0, last_ts - first_ts)
            dur_str = format_time_duration(duration)

            if curr.step_type == StepType.IDLE:
                content = f"idle x{count} over {dur_str}"
            else:
                rc_suffix = f" (rc={last_step.return_code})" if last_step.return_code is not None else ""
                content = f"run failed x{count} over {dur_str}{rc_suffix}"

            synthetic_step = StreamStepItem(
                step_id=last_step.step_id,
                run_id=last_step.run_id,
                step_type=curr.step_type,
                content=content,
                timestamp=last_ts,
                return_code=last_step.return_code,
                collapsed_count=count,
                duration_seconds=duration,
                first_timestamp=first_ts,
                last_timestamp=last_ts,
                metadata={
                    "collapsed_from_count": count,
                    "first_step_id": first_step.step_id,
                    "last_step_id": last_step.step_id,
                },
            )
            collapsed.append(synthetic_step)
            i = j

        return tuple(collapsed), collapsed_steps_count

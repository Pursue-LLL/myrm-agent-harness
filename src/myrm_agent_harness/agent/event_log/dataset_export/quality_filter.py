"""Quality filter — evaluate trace fitness for fine-tuning datasets.

Applies three core quality dimensions:
1. Task outcome (success / failure / cancelled)
2. Content integrity (non-empty, minimum length)
3. Conversation depth (minimum turns)

[INPUT]
- event_log.trace_types::ExecutionTrace, TraceOutcome (POS: Read-side aggregation types)
- dataset_export.protocols::QualityThresholds (POS: Pure type definitions)

[OUTPUT]
- passes_quality: predicate function for trace filtering

[POS]
Stateless quality gate. Returns bool — no scoring, no ranking.
Keeps the pipeline simple and deterministic.
"""

from __future__ import annotations

from ..trace_types import ExecutionTrace, TraceOutcome
from .protocols import QualityThresholds


def passes_quality(trace: ExecutionTrace, thresholds: QualityThresholds) -> bool:
    """Check whether a trace meets quality thresholds for dataset inclusion.

    Args:
        trace: the execution trace to evaluate
        thresholds: filtering parameters

    Returns:
        True if the trace passes all quality checks.
    """
    if thresholds.require_success and trace.outcome != TraceOutcome.SUCCESS:
        return False

    total_turns = len(trace.tool_calls) + len(trace.llm_calls)
    if total_turns < thresholds.min_turns:
        return False

    content_length = len(trace.task_input) + len(trace.output)
    return content_length >= thresholds.min_content_length

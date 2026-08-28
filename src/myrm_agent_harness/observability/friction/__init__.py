"""Task Friction Telemetry Subsystem.

[INPUT]
- types::(FrictionCategory, TaskFrictionEvent, FrictionSummary)
- extractor::FrictionExtractor
- aggregator::FrictionAggregator
- eval_bridge::friction_to_eval_case

[OUTPUT]
- Public exports for task friction events, extraction, aggregation, and Eval Lab feeding

[POS]
Package entry point providing zero-LLM task friction telemetry and model co-evolution pipeline.
"""

from __future__ import annotations

from myrm_agent_harness.observability.friction.aggregator import FrictionAggregator
from myrm_agent_harness.observability.friction.eval_bridge import friction_to_eval_case
from myrm_agent_harness.observability.friction.extractor import FrictionExtractor
from myrm_agent_harness.observability.friction.types import (
    FrictionCategory,
    FrictionSummary,
    TaskFrictionEvent,
)

__all__ = [
    "FrictionAggregator",
    "FrictionCategory",
    "FrictionExtractor",
    "FrictionSummary",
    "TaskFrictionEvent",
    "friction_to_eval_case",
]

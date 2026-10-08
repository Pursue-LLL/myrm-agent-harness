"""Hindsight Experience Replay and Retrospective Reflection Buffer package.

[INPUT]
- toolkits.memory.strategies.hindsight.counterfactual_extractor::CounterfactualRuleExtractor (POS:
  Counterfactual rule extractor deriving actionable hindsight lessons from failure trajectories.)
- toolkits.memory.strategies.hindsight.reflection_buffer::HindsightReflectionBuffer (POS: Retrospective
  reflection buffer storing rules and injecting proactive pre-execution warnings.)
- toolkits.memory.strategies.hindsight.trajectory_scrubber::FailureTrajectoryScrubber (POS: Scrubber for
  failed task trajectories, extracting critical turns and error turning points.)
- toolkits.memory.strategies.hindsight.types::FailureTrajectory, FailureTurn, HindsightRule,
  PreExecutionWarning, ReflectionBufferConfig (POS: Type definitions and contracts for Hindsight Experience
  Replay and Reflection Buffer.)

[OUTPUT]
- Package facade re-exporting 8 public names: CounterfactualRuleExtractor, FailureTrajectory,
  FailureTrajectoryScrubber, FailureTurn, HindsightReflectionBuffer, HindsightRule, PreExecutionWarning,
  ReflectionBufferConfig

[POS]
Hindsight Experience Replay and Retrospective Reflection Buffer package.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.strategies.hindsight.counterfactual_extractor import (
    CounterfactualRuleExtractor,
)
from myrm_agent_harness.toolkits.memory.strategies.hindsight.reflection_buffer import (
    HindsightReflectionBuffer,
)
from myrm_agent_harness.toolkits.memory.strategies.hindsight.tool import (
    HindsightWarningInspectInput,
    create_hindsight_reflection_tool,
)
from myrm_agent_harness.toolkits.memory.strategies.hindsight.trajectory_scrubber import (
    FailureTrajectoryScrubber,
)
from myrm_agent_harness.toolkits.memory.strategies.hindsight.types import (
    FailureTrajectory,
    FailureTurn,
    HindsightRule,
    PreExecutionWarning,
    ReflectionBufferConfig,
)

__all__ = [
    "CounterfactualRuleExtractor",
    "FailureTrajectory",
    "FailureTrajectoryScrubber",
    "FailureTurn",
    "HindsightReflectionBuffer",
    "HindsightRule",
    "HindsightWarningInspectInput",
    "PreExecutionWarning",
    "ReflectionBufferConfig",
    "create_hindsight_reflection_tool",
]

"""Context threshold model downshift and handover package.

[INPUT]
- agent.context_management.downshift.governor::DownshiftGovernor
  (POS: 上下文阈值降级与交接治理层)
- agent.context_management.downshift.schemas::DownshiftCallback, DownshiftConfig,
  DownshiftState, DownshiftTriggerMode, HandoffMemo, ModelTier
  (POS: 降级治理数据契约层)

[OUTPUT]
- DownshiftGovernor and the downshift config/state/callback types

[POS]
Public surface of the context downshift subpackage. Preserves prompt-prefix cache by
switching model tiers instead of rewriting the conversation history when context pressure
crosses a threshold.
"""

from myrm_agent_harness.agent.context_management.downshift.governor import DownshiftGovernor
from myrm_agent_harness.agent.context_management.downshift.schemas import (
    DownshiftCallback,
    DownshiftConfig,
    DownshiftState,
    DownshiftTriggerMode,
    HandoffMemo,
    ModelTier,
)

__all__ = [
    "DownshiftCallback",
    "DownshiftConfig",
    "DownshiftGovernor",
    "DownshiftState",
    "DownshiftTriggerMode",
    "HandoffMemo",
    "ModelTier",
]

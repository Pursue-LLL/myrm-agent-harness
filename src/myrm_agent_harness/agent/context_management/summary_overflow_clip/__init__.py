"""Summary call context overflow tail clipping and single retry guard package.

[INPUT]
- overflow_clip_types: contracts, enums, actions, and outcomes.
- tail_message_clipper: TailMessageClipper.
- overflow_retry_guard: OverflowRetryGuard.
- summary_overflow_clip_suite: SummaryCallOverflowTailClipRetrySuite.

[OUTPUT]
- Exposes all core contracts and master facade for summary overflow tail clipping.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.summary_overflow_clip
- Module: __init__.py
"""

from myrm_agent_harness.agent.context_management.summary_overflow_clip.overflow_clip_types import (
    ClipStrategyKind,
    OverflowClipAction,
    OverflowClipOutcome,
    SummaryOverflowClipConfig,
    SummaryRetryVerdict,
)
from myrm_agent_harness.agent.context_management.summary_overflow_clip.overflow_retry_guard import (
    OverflowRetryGuard,
)
from myrm_agent_harness.agent.context_management.summary_overflow_clip.summary_overflow_clip_suite import (
    SummaryCallOverflowTailClipRetrySuite,
)
from myrm_agent_harness.agent.context_management.summary_overflow_clip.tail_message_clipper import (
    TailMessageClipper,
)

__all__ = [
    "ClipStrategyKind",
    "OverflowClipAction",
    "OverflowClipOutcome",
    "OverflowRetryGuard",
    "SummaryCallOverflowTailClipRetrySuite",
    "SummaryOverflowClipConfig",
    "SummaryRetryVerdict",
    "TailMessageClipper",
]

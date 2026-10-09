"""Domain contracts and data models for compact-before-send token chip and send action honesty.

[INPUT]
- None (pure domain models and primitive types).

[OUTPUT]
- Exports CompactActionPreference, CompactPreflightEstimate, SendButtonDisplaySpec,
  CompactBeforeSendConfig, and CompactChipVerdict.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.compact_chip
- Module: compact_chip_types.py
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CompactActionPreference(str, Enum):
    """User preference determining preflight compaction on next message dispatch."""

    AUTO_COMPACT = "auto_compact"
    FORCE_KEEP_FULL = "force_keep_full"
    FORCE_COMPACT = "force_compact"


class CompactChipVerdict(str, Enum):
    """Determination of chip presentation state in composer."""

    HIDDEN = "hidden"
    COMPACT_WILL_TRIGGER = "compact_will_trigger"
    KEEP_FULL_OVERRIDDEN = "keep_full_overridden"
    MANUAL_COMPACT_REQUESTED = "manual_compact_requested"


@dataclass(frozen=True)
class CompactBeforeSendConfig:
    """Thresholds governing preflight compaction prediction and chip display."""

    stale_threshold_seconds: float = 3600.0  # 1 hour idle triggers stale compact
    pressure_threshold_ratio: float = 0.75  # 75% of context limit triggers pressure compact
    min_display_tokens: int = 500  # Below this threshold, compact chip is not shown


@dataclass(frozen=True)
class CompactPreflightEstimate:
    """Metrics snapshot capturing current context occupancy and compression potential."""

    total_tokens: int
    max_context_tokens: int
    idle_seconds: float
    estimated_compressible_tokens: int
    is_stale: bool
    is_pressured: bool


@dataclass(frozen=True)
class SendButtonDisplaySpec:
    """Resolved display metadata for composer send button and compact chip."""

    verdict: CompactChipVerdict
    will_compact: bool
    primary_send_label: str
    tooltip: str
    chip_visible: bool
    chip_text: str
    estimated_tokens: int

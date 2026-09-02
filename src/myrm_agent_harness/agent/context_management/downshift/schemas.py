"""Schemas for Context Threshold Model Downshift and Handoff.

[INPUT]
None (pure domain schemas).

[OUTPUT]
- DownshiftTriggerMode: Trigger condition enum (TOKEN_PERCENT, WORK_UNITS, BOTH).
- ModelTier: Tier classification enum (PREMIUM, ECONOMY).
- HandoffMemo: Deterministic structured handover note.
- DownshiftConfig: Configuration parameters for context governor.
- DownshiftState: Runtime tracking state per session.
- DownshiftCallback: Callable signature for downstream notification.

[POS]
Domain models for context threshold-driven model downshifting and handover memo extraction.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum


class DownshiftTriggerMode(str, Enum):
    """Trigger mode for model downshift."""

    TOKEN_PERCENT = "token_percent"
    WORK_UNITS = "work_units"
    BOTH = "both"


class ModelTier(str, Enum):
    """Model execution tier classification."""

    PREMIUM = "premium"
    ECONOMY = "economy"


@dataclass
class HandoffMemo:
    """Deterministic structured handover memo extracted from SessionNotes."""

    session_id: str
    turn_index: int
    source_model: str
    target_tier: ModelTier
    task_spec: str = ""
    current_state: str = ""
    files_and_functions: str = ""
    errors_and_corrections: str = ""
    remaining_steps: str = ""
    created_at: float = field(default_factory=time.time)

    def to_system_supplement(self) -> str:
        """Format as prompt-safe supplementary instruction without cache prefix mutation."""
        parts: list[str] = [
            "### [CONTEXT HANDOVER MEMO · DETERMINISTIC STATE TRANSFER]",
            f"Source Model: {self.source_model} -> Target Tier: {self.target_tier.value.upper()}",
        ]
        if self.task_spec:
            parts.append(f"Task Objective:\n{self.task_spec.strip()}")
        if self.current_state:
            parts.append(f"Active State & Next Actions:\n{self.current_state.strip()}")
        if self.files_and_functions:
            parts.append(f"Key Files & Functions:\n{self.files_and_functions.strip()}")
        if self.errors_and_corrections:
            parts.append(f"Known Corrections:\n{self.errors_and_corrections.strip()}")
        if self.remaining_steps:
            parts.append(f"Remaining Steps:\n{self.remaining_steps.strip()}")
        return "\n\n".join(parts)


@dataclass
class DownshiftConfig:
    """Configuration for Context Cost Governor."""

    enabled: bool = False
    trigger_mode: DownshiftTriggerMode = DownshiftTriggerMode.TOKEN_PERCENT
    context_usage_pct_threshold: float = 0.60
    wu_threshold: float = 50.0
    max_consecutive_economy_failures: int = 2
    auto_fallback_up: bool = True


@dataclass
class DownshiftState:
    """Runtime tracking state for a session's downshift lifecycle."""

    session_id: str
    current_tier: ModelTier = ModelTier.PREMIUM
    is_downshifted: bool = False
    downshifted_turn: int | None = None
    downshift_reason: str = ""
    consecutive_economy_failures: int = 0
    fallback_up_count: int = 0
    handoff_memo: HandoffMemo | None = None
    manually_revoked: bool = False


DownshiftCallback = Callable[[DownshiftState], Awaitable[None] | None]

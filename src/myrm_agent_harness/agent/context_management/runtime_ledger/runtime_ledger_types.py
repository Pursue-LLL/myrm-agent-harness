# [INPUT]: None
# [OUTPUT]: LedgerInjectionResult, LedgerUpdatePolicy, QuotaConstraint, RuntimeLedgerConfig, RuntimeStateSnapshot, TodoProgress
# [POS]: agent/context_management/runtime_ledger/runtime_ledger_types.py

"""Domain models and contracts for deterministic runtime state ledger and cache-friendly tail injection.

[INPUT]
- None (Self-contained domain definitions for runtime status dashboards).

[OUTPUT]
- LedgerUpdatePolicy: Enumeration governing replace vs. append update strategies.
- QuotaConstraint: Finite quota constraint counter (e.g. max 3 phone calls).
- TodoProgress: Itemized task checklist tracking step progression.
- RuntimeStateSnapshot: Deterministically compiled status snapshot.
- RuntimeLedgerConfig: Capacity limits, tag name, and policy configuration.
- LedgerInjectionResult: Outcome holding rendered tag string and injection statistics.

[POS]
Domain model layer for deterministic runtime state ledger injection in context management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class LedgerUpdatePolicy(str, Enum):
    """Strategy for updating runtime status tags across successive dialogue turns."""

    REPLACE = "replace"
    APPEND = "append"


@dataclass(frozen=True)
class QuotaConstraint:
    """Explicit quota allowance and current usage limit."""

    name: str
    max_limit: int
    used_count: int
    unit: str = "calls"

    @property
    def remaining(self) -> int:
        return max(0, self.max_limit - self.used_count)

    @property
    def is_exhausted(self) -> bool:
        return self.used_count >= self.max_limit


@dataclass(frozen=True)
class TodoProgress:
    """Individual action item in task checklist."""

    step_id: str
    title: str
    is_completed: bool


@dataclass(frozen=True)
class RuntimeStateSnapshot:
    """Immutable, deterministically compiled status snapshot for model steering."""

    session_id: str
    turn_index: int
    tool_call_counts: Mapping[str, int]
    constraints: Sequence[QuotaConstraint]
    todos: Sequence[TodoProgress]
    current_timestamp_iso: str
    recent_milestones: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class RuntimeLedgerConfig:
    """Settings controlling status tag syntax, token ceilings, and placement."""

    update_policy: LedgerUpdatePolicy = LedgerUpdatePolicy.REPLACE
    max_ledger_tokens: int = 400
    status_tag_name: str = "agent_status"
    enable_timestamp: bool = True


@dataclass(frozen=True)
class LedgerInjectionResult:
    """Outcome container of rendering and injecting ledger status block."""

    rendered_tag: str
    token_estimate: int
    policy_used: LedgerUpdatePolicy
    injected_into_tail: bool = True

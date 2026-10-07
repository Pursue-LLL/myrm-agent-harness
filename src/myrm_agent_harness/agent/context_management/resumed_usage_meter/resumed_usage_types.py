"""Data contracts and schemas for resumed session history token exclusion and net run usage metering.

Distinguishes physical model throughput from incremental task consumption,
ensuring fair billing and eliminating duplicate charges upon session resumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ResumptionBaseline:
    """Snapshot of prior session scale captured at the moment of resumption."""

    session_id: str
    resumed_history_tokens: int
    resumed_turn_count: int
    resumed_at_iso: str
    prior_cumulative_cost: float = 0.0


@dataclass(frozen=True)
class RawTurnUsage:
    """Raw token usage numbers reported by the model inference provider."""

    gross_prompt_tokens: int
    completion_tokens: int
    cached_prompt_tokens: int = 0
    model_name: str = "default"


@dataclass(frozen=True)
class NetRunUsage:
    """True incremental usage belonging specifically to the active task execution."""

    net_prompt_tokens: int
    completion_tokens: int
    net_billable_tokens: int
    excluded_history_tokens: int
    cache_hit_ratio: float
    gross_physical_tokens: int


@dataclass(frozen=True)
class UsageBillingLedgerRecord:
    """Auditable ledger entry documenting token allocation and billing metrics for a turn."""

    record_id: str
    session_id: str
    turn_index: int
    is_resumed_turn: bool
    raw_usage: RawTurnUsage
    net_usage: NetRunUsage
    computed_cost: float


@dataclass(frozen=True)
class SessionUsageSummary:
    """Consolidated lifetime and incremental usage metrics across the session lifecycle."""

    session_id: str
    total_turns: int
    lifetime_gross_tokens: int
    lifetime_net_run_tokens: int
    total_excluded_history_tokens: int
    total_cost: float

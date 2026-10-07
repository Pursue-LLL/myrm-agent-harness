"""Type definitions for Micro-Compaction and Amortized Turn Context Reclamation.

Provides immutable configurations, exchange structures, and running summary states
implementing amortized instalments, zero-compaction user message preservation, and
three-zone context protection.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- MicroCompactionConfig: Configuration governing micro-compaction cadence, thresholds, and protections.
- ExchangeBlock: An exchange representing assistant narrative and subsequent tool outputs in a turn.
- RunningSummaryState: Immutable state tracking the single running summary across amortized instalments.
- MicroCompactionResult: Result emitted after evaluating or executing an amortized micro-compaction cycle.

[POS]
Type definitions for Micro-Compaction and Amortized Turn Context Reclamation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MicroCompactionConfig:
    """Configuration governing micro-compaction cadence, thresholds, and protections."""

    head_protected_turns: int = 1
    tail_protected_turns: int = 2
    compact_every_n_turns: int = 1
    max_running_summary_tokens: int = 2000
    max_retries_per_exchange: int = 3
    preserve_user_messages: bool = True


@dataclass(frozen=True)
class ExchangeBlock:
    """An exchange representing assistant narrative and subsequent tool outputs in a turn."""

    exchange_id: str
    turn_index: int
    assistant_content: str | None
    tool_contents: tuple[str, ...]
    total_chars: int
    failure_count: int = 0


@dataclass(frozen=True)
class RunningSummaryState:
    """Immutable state tracking the single running summary across amortized instalments."""

    session_id: str
    summary_text: str
    absorbed_exchanges_count: int
    last_absorbed_turn_index: int
    defrag_count: int
    estimated_summary_tokens: int


@dataclass(frozen=True)
class MicroCompactionResult:
    """Result emitted after evaluating or executing an amortized micro-compaction cycle."""

    session_id: str
    is_compacted: bool
    absorbed_exchange_id: str | None
    running_summary: RunningSummaryState
    reclaimed_chars: int
    skipped_due_to_strikes: bool = False
    diagnostics: str = ""

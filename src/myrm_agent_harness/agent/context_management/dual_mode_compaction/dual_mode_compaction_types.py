"""Types and schemas for proactive watermark compaction and reactive 400 self-healing.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- CompactionTriggerKind: Classification of how compaction was triggered.
- ProviderOverflowKind: Normalized provider overflow classification.
- ContextWindowBudgetConfig: Configuration governing active watermark limits and overflow reserves.
- CompactableMessage: Message item carrying text, estimated tokens, and preservation flags.
- CompactionExecutionResult: Outcome of a compaction operation.
- SelfHealingAuditReceipt: Cryptographic audit receipt recorded when reactive self-healing succeeds.

[POS]
Types and schemas for proactive watermark compaction and reactive 400 self-healing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CompactionTriggerKind(str, Enum):
    """Classification of how compaction was triggered."""

    PROACTIVE_WATERMARK = "proactive_watermark"
    REACTIVE_400_SELF_HEAL = "reactive_400_self_heal"
    MANUAL = "manual"


class ProviderOverflowKind(str, Enum):
    """Normalized provider overflow classification."""

    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
    MAX_TOKENS_EXCEEDED = "max_tokens_exceeded"
    PROMPT_TOO_LONG = "prompt_too_long"
    UNKNOWN_OVERFLOW = "unknown_overflow"


@dataclass(frozen=True)
class ContextWindowBudgetConfig:
    """Configuration governing active watermark limits and overflow reserves."""

    context_window_tokens: int = 128000
    reserve_tokens: int = 8192
    proactive_threshold_ratio: float = 0.85
    emergency_trim_ratio: float = 0.35
    max_self_healing_retries: int = 3


@dataclass(frozen=True)
class CompactableMessage:
    """Message item carrying text, estimated tokens, and preservation flags."""

    message_id: str
    role: str
    content: str
    estimated_tokens: int
    is_pinned: bool = False
    is_system_invariant: bool = False
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CompactionExecutionResult:
    """Outcome of a compaction operation."""

    trigger_kind: CompactionTriggerKind
    original_tokens: int
    compacted_tokens: int
    tokens_saved: int
    retained_messages_count: int
    compacted_summary: str
    preserved_pinned_count: int


@dataclass(frozen=True)
class SelfHealingAuditReceipt:
    """Cryptographic audit receipt recorded when reactive self-healing succeeds."""

    session_id: str
    retry_attempt: int
    detected_overflow_kind: ProviderOverflowKind
    original_error_message: str
    tokens_before_retry: int
    tokens_after_retry: int
    recovered_successfully: bool
    audit_hash: str

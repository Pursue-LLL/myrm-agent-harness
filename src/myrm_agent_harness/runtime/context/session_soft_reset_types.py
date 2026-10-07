"""Data contracts and types for session state soft-reset and instant memory consolidation.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ResetTriggerKind: The source or channel that initiated the session soft-reset.
- VaultedMemoryItem: An individual distilled memory item extracted prior to context window clearing.
- VaultedConsolidatedMemory: Vaulted memory package holding all consolidated facts from the pre-reset
  conversation.
- SoftResetExecutionResult: Outcome of soft-reset: Short-term window cleared while baseline & memories
  seamlessly reloaded.

[POS]
Data contracts and types for session state soft-reset and instant memory consolidation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ResetTriggerKind(StrEnum):
    """The source or channel that initiated the session soft-reset."""

    EXPLICIT_SLASH_COMMAND = "slash_command"  # e.g., /reset, /clear
    UI_ACTION_BUTTON = "ui_action"  # WebUI or Desktop clear/reset button
    NATURAL_LANGUAGE_INTENT = "natural_language"  # e.g., "重新开始聊", "聊乱了翻篇"


@dataclass(frozen=True)
class VaultedMemoryItem:
    """An individual distilled memory item extracted prior to context window clearing."""

    item_id: str
    category: str  # "preference", "fact", "lesson"
    content: str
    extracted_from_turn: int = 0


@dataclass(frozen=True)
class VaultedConsolidatedMemory:
    """Vaulted memory package holding all consolidated facts from the pre-reset conversation."""

    session_id: str
    vaulted_at: float
    items: tuple[VaultedMemoryItem, ...] = field(default_factory=tuple)
    pre_reset_message_count: int = 0
    summary_digest: str = ""


@dataclass(frozen=True)
class SoftResetExecutionResult:
    """Outcome of soft-reset: Short-term window cleared while baseline & memories seamlessly reloaded."""

    session_id: str
    trigger_kind: ResetTriggerKind
    cleared_message_count: int
    vaulted_memory: VaultedConsolidatedMemory
    reloaded_baseline_tokens: int
    system_baseline_prompt: str
    acknowledgment_message: str

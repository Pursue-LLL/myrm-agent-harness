# ============================================================================
# # Context Pinning & Transparent Compaction Inspector Types (Item 146)
# # Strict typed contracts for user context pins, zero-pruning guarantees,
# # and frontend transparent compaction inspector cards.
# ============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class PinnedItemType(StrEnum):
    """Categorization for pinned context artifacts."""

    MESSAGE = "message"  # Entire chat message pinned
    FACT = "fact"  # Extracted key fact or rule pinned
    FILE_PATH = "file_path"  # High-priority file path pinned
    DECISION = "decision"  # Irreversible architecture/technical decision


@dataclass(slots=True)
class PinnedContextItem:
    """Represents a user-pinned context item protected with zero-pruning guarantee."""

    pin_id: str
    item_type: PinnedItemType
    content: str
    target_id: str | None = None  # E.g. message_id or file path
    title: str = ""
    pinned_at: float = field(default_factory=time.time)
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str | int | float | bool | None]:
        """Serializes pinned item to flat dictionary."""
        return {
            "pin_id": self.pin_id,
            "item_type": str(self.item_type),
            "content": self.content,
            "target_id": self.target_id,
            "title": self.title,
            "pinned_at": self.pinned_at,
        }


@dataclass(slots=True)
class CompactionInspectorCardData:
    """Data contract for the transparent compaction inspector card rendered in UI."""

    card_id: str
    chat_id: str
    pre_tokens: int
    post_tokens: int
    saved_tokens: int
    savings_ratio: float
    compacted_turns_count: int
    preserved_pinned_count: int
    structured_summary_text: str
    key_decisions: list[str] = field(default_factory=list)
    pinned_items_preview: list[str] = field(default_factory=list)
    is_user_editable: bool = True
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | int | float | bool | list[str]]:
        """Converts inspector card to dictionary for WebSocket / REST payload."""
        return {
            "card_id": self.card_id,
            "chat_id": self.chat_id,
            "pre_tokens": self.pre_tokens,
            "post_tokens": self.post_tokens,
            "saved_tokens": self.saved_tokens,
            "savings_ratio": round(self.savings_ratio, 4),
            "compacted_turns_count": self.compacted_turns_count,
            "preserved_pinned_count": self.preserved_pinned_count,
            "structured_summary_text": self.structured_summary_text,
            "key_decisions": list(self.key_decisions),
            "pinned_items_preview": list(self.pinned_items_preview),
            "is_user_editable": self.is_user_editable,
            "created_at": self.created_at,
        }

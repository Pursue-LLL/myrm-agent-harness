"""Data contracts and models for sparse semantic mutation engine.

Provides strongly typed schemas for slot actions, kinds, semantic slots,
sparse action masks, and final mutation payloads.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SlotAction(StrEnum):
    """Action to perform on an individual semantic slot."""

    RETAIN = "retain"
    OVERWRITE = "overwrite"
    APPEND = "append"
    REMOVE = "remove"


class SlotKind(StrEnum):
    """Structural type of a semantic slot."""

    KEY_VALUE = "key_value"
    LIST_ITEM = "list_item"
    CLAUSE = "clause"
    PROSE_LINE = "prose_line"


class SemanticSlot(BaseModel):
    """An atomic semantic unit extracted from compound structured text."""

    key: str = Field(..., description="Normalized slot identifier")
    value: str = Field(..., description="Payload or parameter value of the slot")
    raw_line: str = Field(..., description="Original raw line for verbatim retention")
    indent_level: int = Field(default=0, description="Leading whitespace indentation count")
    bullet_prefix: str = Field(default="", description="Bullet marker like '- ', '* ', or '1. '")
    separator: str = Field(default=": ", description="Key-value delimiter like ': ' or '：'")
    kind: SlotKind = Field(default=SlotKind.LIST_ITEM, description="Syntactic kind of slot")
    line_index: int = Field(default=0, description="Source line zero-based index")
    is_negated: bool = Field(default=False, description="Whether slot denotes explicit removal/prohibition")
    clause_delimiter: str = Field(default="", description="Delimiter between clauses on the same line")


class SparseMaskItem(BaseModel):
    """Diff directive for a single slot in the sparse mutation plan."""

    slot_key: str
    action: SlotAction
    old_value: str | None = None
    new_value: str | None = None
    raw_diff: str = ""


class SparseMutationResult(BaseModel):
    """Outcome of a sparse semantic mutation operation."""

    original_text: str
    mutated_text: str
    mask_items: list[SparseMaskItem]
    is_mutated: bool
    retained_count: int
    overwritten_count: int
    appended_count: int
    removed_count: int
    summary: str


__all__ = [
    "SemanticSlot",
    "SlotAction",
    "SlotKind",
    "SparseMaskItem",
    "SparseMutationResult",
]

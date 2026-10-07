"""Virtual paged code context tiering and swap engine types.

Defines page lifecycle states, AST symbol stubs, virtual code page contracts,
page-fault events, and context stability metrics for OS-inspired code paging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PageLifecycleState(StrEnum):
    """Lifecycle state of a virtual code page within tiered memory."""

    CORE_RESIDENT = "core_resident"  # Active in inference context (≤4000 tokens)
    ARCHIVED_PAGE = "archived_page"  # Offloaded to fast local cache; stub retained
    EVICTED = "evicted"  # Completely discarded from working memory


@dataclass(frozen=True)
class CodeSymbolStub:
    """Lightweight persistent signature stub for classes and functions."""

    symbol_name: str
    kind: str  # "class" | "function" | "method"
    signature: str
    doc_summary: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class VirtualCodePage:
    """A standard 2KB~4KB virtual code page holding AST blocks and symbol metadata."""

    page_id: str
    file_path: str
    content: str
    ast_symbols: tuple[CodeSymbolStub, ...]
    token_count: int
    is_dirty: bool = False
    lifecycle_state: PageLifecycleState = PageLifecycleState.CORE_RESIDENT
    last_accessed_tick: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PageFaultEvent:
    """Event triggered when referencing a symbol present in an archived page."""

    page_id: str
    file_path: str
    requested_symbol: str
    resolved: bool
    reason: str


@dataclass(frozen=True)
class PageSwapAudit:
    """Diagnostic audit verifying context token stability across multi-file edits."""

    active_core_tokens: int
    max_budget_tokens: int
    resident_pages_count: int
    archived_pages_count: int
    total_page_faults: int
    total_swapped_out_pages: int
    is_budget_exceeded: bool
    stability_variance_ratio: float  # Variance ratio compared to budget limit

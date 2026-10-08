"""Types and data structures for table detection, last-round protection, and atomic pruning.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- TableProtectionMode: Strategy for handling tables during context pruning.
- MarkdownTableBlock: Extracted markdown table structure with boundaries and parsed rows.
- TablePruningReceipt: Auditable receipt documenting table detection, protection, and syntax preservation.

[POS]
Types and data structures for table detection, last-round protection, and atomic pruning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class TableProtectionMode(str, Enum):
    """Strategy applied to markdown tables during context pruning."""

    PRESERVE_ENTIRE_TABLE = "preserve_entire_table"
    SEMANTIC_COMPACT_DIGEST = "semantic_compact_digest"
    SAFE_ATOMIC_TRUNCATE = "safe_atomic_truncate"


@dataclass(frozen=True)
class MarkdownTableBlock:
    """Represents a discovered markdown table inside message text."""

    table_id: str
    start_char_index: int
    end_char_index: int
    raw_markdown: str
    headers: List[str]
    rows: List[List[str]]
    row_count: int
    column_count: int
    is_well_formed: bool


@dataclass(frozen=True)
class TablePruningReceipt:
    """Receipt certifying table protection actions and syntax integrity."""

    receipt_id: str
    session_id: str
    total_tables_detected: int
    last_round_tables_preserved: int
    historical_tables_compacted: int
    historical_tables_atomically_truncated: int
    syntax_integrity_maintained: bool
    processed_at_iso: str

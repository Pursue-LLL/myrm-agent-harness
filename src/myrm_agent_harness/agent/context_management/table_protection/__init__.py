"""History assistant table prune and last-round table protection package facade.

[INPUT]
- None (package facade re-exporting detector, protector, types, and orchestration suite)

[OUTPUT]
- TableProtectionMode
- MarkdownTableBlock
- TablePruningReceipt
- MarkdownTableDetector
- TablePruningProtector
- HistoryAssistantTablePruneAndLastRoundProtectSuite

[POS]
History assistant table prune and last-round table protection package facade.
"""

from __future__ import annotations

from .markdown_table_detector import MarkdownTableDetector
from .table_protection_suite import HistoryAssistantTablePruneAndLastRoundProtectSuite
from .table_protection_types import (
    MarkdownTableBlock,
    TableProtectionMode,
    TablePruningReceipt,
)
from .table_pruning_protector import TablePruningProtector

__all__ = [
    "TableProtectionMode",
    "MarkdownTableBlock",
    "TablePruningReceipt",
    "MarkdownTableDetector",
    "TablePruningProtector",
    "HistoryAssistantTablePruneAndLastRoundProtectSuite",
]

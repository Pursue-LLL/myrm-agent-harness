"""Main suite orchestrating history assistant table pruning and last-round table protection.

[INPUT]
- session_id: str identifier of current conversation
- messages: List[Dict[str, str]] conversation message history

[OUTPUT]
- HistoryAssistantTablePruneAndLastRoundProtectSuite: Main orchestrator for table detection and last-round protection.

[POS]
Main suite orchestrating history assistant table pruning and last-round table protection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import uuid

from .markdown_table_detector import MarkdownTableDetector
from .table_protection_types import (
    MarkdownTableBlock,
    TableProtectionMode,
    TablePruningReceipt,
)
from .table_pruning_protector import TablePruningProtector


class HistoryAssistantTablePruneAndLastRoundProtectSuite:
    """Orchestrates deep preservation for last-round assistant tables and safe syntax compaction for history."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._receipts: List[TablePruningReceipt] = []

    @property
    def session_id(self) -> str:
        """Return target session ID."""
        return self._session_id

    def detect_tables_in_text(self, text: str) -> List[MarkdownTableBlock]:
        """Detect and return all markdown tables present in text."""
        return MarkdownTableDetector.detect_tables(text)

    def prune_and_protect_messages(
        self,
        messages: List[Dict[str, str]],
        compact_historical_tables: bool = True,
    ) -> Tuple[List[Dict[str, str]], TablePruningReceipt]:
        """Process messages: strictly preserve last-round assistant tables while compacting historical tables."""
        if not messages:
            receipt = TablePruningReceipt(
                receipt_id=f"tpr_{uuid.uuid4().hex[:8]}",
                session_id=self._session_id,
                total_tables_detected=0,
                last_round_tables_preserved=0,
                historical_tables_compacted=0,
                historical_tables_atomically_truncated=0,
                syntax_integrity_maintained=True,
                processed_at_iso=datetime.now(timezone.utc).isoformat(),
            )
            return [], receipt

        # 1. Identify index of last assistant message
        last_assistant_idx: Optional[int] = None
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].get("role") == "assistant":
                last_assistant_idx = idx
                break

        total_detected = 0
        last_round_preserved = 0
        historical_compacted = 0
        processed_messages: List[Dict[str, str]] = []

        for idx, msg in enumerate(messages):
            role = msg.get("role", "")
            content = msg.get("content", "")
            tables = MarkdownTableDetector.detect_tables(content)
            total_detected += len(tables)

            if not tables or role != "assistant":
                # User/system or assistant without tables remains unchanged
                processed_messages.append(dict(msg))
                continue

            if idx == last_assistant_idx:
                # Deep protection: Last-round assistant tables are preserved 100% intact
                last_round_preserved += len(tables)
                processed_messages.append(dict(msg))
            else:
                # Historical assistant message: compact tables if requested
                new_content = content
                if compact_historical_tables:
                    # Compact each table in reverse order so character offsets remain valid
                    for tbl in reversed(tables):
                        new_content = TablePruningProtector.apply_table_protection(
                            text=new_content,
                            table=tbl,
                            mode=TableProtectionMode.SEMANTIC_COMPACT_DIGEST,
                        )
                        historical_compacted += 1

                new_msg = dict(msg)
                new_msg["content"] = new_content
                processed_messages.append(new_msg)

        receipt = TablePruningReceipt(
            receipt_id=f"tpr_{uuid.uuid4().hex[:8]}",
            session_id=self._session_id,
            total_tables_detected=total_detected,
            last_round_tables_preserved=last_round_preserved,
            historical_tables_compacted=historical_compacted,
            historical_tables_atomically_truncated=0,
            syntax_integrity_maintained=True,
            processed_at_iso=datetime.now(timezone.utc).isoformat(),
        )
        self._receipts.append(receipt)

        return processed_messages, receipt

    def get_receipts(self) -> List[TablePruningReceipt]:
        """Retrieve audit receipts of all table pruning operations."""
        return list(self._receipts)

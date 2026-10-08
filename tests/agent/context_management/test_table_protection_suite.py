"""Unit tests for HistoryAssistantTablePruneAndLastRoundProtectSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    HistoryAssistantTablePruneAndLastRoundProtectSuite,
    MarkdownTableBlock,
    MarkdownTableDetector,
    TableProtectionMode,
    TablePruningProtector,
    TablePruningReceipt,
)


def test_markdown_table_detector_parsing_and_boundaries() -> None:
    """Test detecting and parsing markdown table structure, headers, rows, and boundaries."""
    text = (
        "Here is the evaluation matrix:\n\n"
        "| Model | Score | Latency |\n"
        "| :--- | :---: | ---: |\n"
        "| Claude-3.7 | 95 | 120ms |\n"
        "| GPT-4o | 92 | 90ms |\n"
        "| DeepSeek-R1 | 94 | 150ms |\n\n"
        "End of evaluation report."
    )

    tables = MarkdownTableDetector.detect_tables(text)
    assert len(tables) == 1

    tbl = tables[0]
    assert tbl.headers == ["Model", "Score", "Latency"]
    assert tbl.column_count == 3
    assert tbl.row_count == 3
    assert tbl.rows[0] == ["Claude-3.7", "95", "120ms"]
    assert tbl.rows[1] == ["GPT-4o", "92", "90ms"]
    assert tbl.rows[2] == ["DeepSeek-R1", "94", "150ms"]
    assert tbl.is_well_formed is True
    assert "Here is the evaluation" not in tbl.raw_markdown


def test_last_round_assistant_table_deep_protection() -> None:
    """Test that the last-round assistant message table is 100% deeply protected and unpruned."""
    suite = HistoryAssistantTablePruneAndLastRoundProtectSuite(session_id="sess-table-001")

    hist_table = (
        "| Step | Task | Status |\n"
        "|---|---|---|\n"
        "| 1 | Setup DB | Done |\n"
        "| 2 | Add API | Done |\n"
        "| 3 | Run E2E | Done |\n"
        "| 4 | Deploy | Done |\n"
    )

    last_table = (
        "| Issue ID | Severity | Root Cause |\n"
        "|---|---|---|\n"
        "| BUG-101 | High | Null pointer in worker |\n"
        "| BUG-102 | Medium | Race condition in cache |\n"
    )

    messages = [
        {"role": "user", "content": "How did phase 1 go?"},
        {"role": "assistant", "content": f"Here is the phase 1 log:\n{hist_table}"},
        {"role": "user", "content": "What about the remaining issues?"},
        {"role": "assistant", "content": f"Here are the active bugs:\n{last_table}"},
    ]

    processed, receipt = suite.prune_and_protect_messages(messages, compact_historical_tables=True)

    assert len(processed) == 4
    assert receipt.last_round_tables_preserved == 1
    assert receipt.historical_tables_compacted == 1

    # Last assistant message must retain table exactly intact
    assert last_table in processed[3]["content"]

    # Historical assistant message should have had its table compacted
    hist_content = processed[1]["content"]
    assert "rows omitted for brevity" in hist_content
    # But it must remain a valid table with headers and closure
    assert "| Step | Task | Status |" in hist_content


def test_historical_assistant_table_semantic_compaction_and_valid_syntax() -> None:
    """Test that historical bulky tables fold into syntax-valid, properly closed markdown tables."""
    raw_table = (
        "| ID | Service | Metric A | Metric B |\n"
        "|---|---|---|---|\n"
        + "\n".join(f"| {i} | svc-{i} | {i*10} | {i*20} |" for i in range(1, 11))
    )

    tables = MarkdownTableDetector.detect_tables(raw_table)
    assert len(tables) == 1

    folded = TablePruningProtector.compact_table_with_valid_syntax(tables[0], max_rows_to_keep=3)

    # Validate table syntax properties
    lines = [line.strip() for line in folded.strip().split("\n")]
    assert len(lines) == 6  # header + separator + kept_row_1 + kept_row_2 + folded_summary_row + last_row
    assert lines[0] == "| ID | Service | Metric A | Metric B |"
    assert lines[1] == "| --- | --- | --- | --- |"
    assert "rows omitted for brevity" in lines[4]
    assert lines[5] == "| 10 | svc-10 | 100 | 200 |"

    # Verify detector can successfully re-parse the folded output as a valid table
    re_parsed = MarkdownTableDetector.detect_tables(folded)
    assert len(re_parsed) == 1
    assert re_parsed[0].is_well_formed is True


def test_table_pruning_receipt_audit_integrity() -> None:
    """Test that table pruning receipts maintain accurate counts and syntax integrity flags."""
    suite = HistoryAssistantTablePruneAndLastRoundProtectSuite(session_id="sess-table-002")

    messages = [
        {"role": "user", "content": "Hello"},
        {
            "role": "assistant",
            "content": "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |\n| 7 | 8 |\n",
        },
        {"role": "user", "content": "Thanks"},
        {
            "role": "assistant",
            "content": "| C | D |\n|---|---|\n| 9 | 10 |\n",
        },
    ]

    _, receipt = suite.prune_and_protect_messages(messages, compact_historical_tables=True)

    assert receipt.receipt_id.startswith("tpr_")
    assert receipt.session_id == "sess-table-002"
    assert receipt.total_tables_detected == 2
    assert receipt.last_round_tables_preserved == 1
    assert receipt.historical_tables_compacted == 1
    assert receipt.syntax_integrity_maintained is True
    assert len(suite.get_receipts()) == 1

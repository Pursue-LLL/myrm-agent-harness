"""Tests for memory import reliability types (source label shape contract).

The framework validates only the label shape: product-owned source names must
round-trip untouched, and malformed labels must fail fast at the boundary.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from myrm_agent_harness.toolkits.memory.reliability import (
    MemoryImportDryRunResult,
    MemoryImportDryRunSummary,
)


class TestMemoryImportSourceContract:
    """Source labels are business-defined; the framework enforces shape only."""

    @pytest.mark.parametrize(
        "source",
        [
            "native_json",
            "myrm_archive",
            "agentmemory",
            "claude_code_jsonl",
            "hermes",
            "openclaw",
            "cursor_rules",
            "codex",
            "claude",
            "mem0",
            "chatgpt",
            "pi",
            "plur",
            "pasted_memory",
            "unknown",
        ],
    )
    def test_dry_run_summary_accepts_business_sources(self, source: str) -> None:
        summary = MemoryImportDryRunSummary(
            source=source,
            version="1",
            total_items=0,
            mapped_items=0,
            unmapped_items=0,
            status="ready",
        )
        assert summary.source == source

    def test_new_business_source_needs_no_framework_change(self) -> None:
        """A source the framework never enumerated still round-trips."""

        summary = MemoryImportDryRunSummary(
            source="future_assistant_export",
            version="1",
            total_items=0,
            mapped_items=0,
            unmapped_items=0,
            status="ready",
        )
        assert summary.source == "future_assistant_export"

    @pytest.mark.parametrize(
        "malformed",
        ["", "Upper", "has space", "has-dash", "1leading_digit", "x" * 65],
    )
    def test_malformed_source_labels_rejected(self, malformed: str) -> None:
        with pytest.raises(ValidationError):
            MemoryImportDryRunSummary(
                source=malformed,
                version="1",
                total_items=0,
                mapped_items=0,
                unmapped_items=0,
                status="ready",
            )

    def test_claude_source_round_trip_in_result(self) -> None:
        result = MemoryImportDryRunResult(
            summary=MemoryImportDryRunSummary(
                source="claude",
                version="1",
                total_items=0,
                mapped_items=0,
                unmapped_items=0,
                status="ready",
            ),
            mappings=[],
            warnings=[],
            normalized_data={},
        )
        assert result.summary.source == "claude"

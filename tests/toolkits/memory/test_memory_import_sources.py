"""Tests for memory import reliability types (competitor source literals)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from myrm_agent_harness.toolkits.memory.reliability import (
    MemoryImportDryRunResult,
    MemoryImportDryRunSummary,
)


class TestMemoryImportSourceLiteral:
    """Ensure competitor import sources accepted by dry-run models include claude."""

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
            "unknown",
        ],
    )
    def test_dry_run_summary_accepts_known_sources(self, source: str) -> None:
        summary = MemoryImportDryRunSummary(
            source=source,  # type: ignore[arg-type]
            version="1",
            total_items=0,
            mapped_items=0,
            unmapped_items=0,
            status="ready",
        )
        assert summary.source == source

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

    def test_invalid_source_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MemoryImportDryRunSummary(
                source="not_a_real_source",  # type: ignore[arg-type]
                version="1",
                total_items=0,
                mapped_items=0,
                unmapped_items=0,
                status="ready",
            )

"""Tests for ADR discovery and MADR status filtering."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.agent.workspace_rules.adr_scanner import (
    is_adr_active,
    parse_adr_status,
    scan_adr_rules,
)


class TestADRStatusParser:
    def test_parse_madr_list_status(self) -> None:
        content = """# 0001: Use SQLite

* Status: accepted
* Date: 2026-08-31

## Context
Need local storage.
"""
        assert parse_adr_status(content) == "accepted"
        assert is_adr_active(content) is True

    def test_parse_deprecated_status(self) -> None:
        content = """# 0002: Use Monolith

* Status: deprecated by ADR-0003
* Date: 2026-09-01
"""
        assert parse_adr_status(content) == "deprecated"
        assert is_adr_active(content) is False

    def test_parse_superseded_status(self) -> None:
        content = """# 0003: Old Protocol

* Status: superseded
"""
        assert parse_adr_status(content) == "superseded"
        assert is_adr_active(content) is False

    def test_parse_frontmatter_status(self) -> None:
        content = """---
status: "active"
date: 2026-09-02
---
# Modern Stack
"""
        assert parse_adr_status(content) == "active"
        assert is_adr_active(content) is True

    def test_parse_bold_and_bracketed_status(self) -> None:
        content = """# 0004: Clean Architecture
**Status:** accepted
* Date: 2026-09-03
"""
        assert parse_adr_status(content) == "accepted"
        assert is_adr_active(content) is True

        content_deprecated = """# 0005: Old Framework
* **Status:** deprecated
"""
        assert parse_adr_status(content_deprecated) == "deprecated"
        assert is_adr_active(content_deprecated) is False

        content_bracketed = """# 0006: Decision
Status: [accepted]
"""
        assert parse_adr_status(content_bracketed) == "accepted"
        assert is_adr_active(content_bracketed) is True

    def test_defaults_to_accepted_when_no_status(self) -> None:
        content = """# Unversioned Note
We decided to adopt UV.
"""
        assert parse_adr_status(content) == "accepted"
        assert is_adr_active(content) is True


class TestScanADRRules:
    def test_scans_only_active_adrs(self, tmp_path: Path) -> None:
        decisions_dir = tmp_path / "docs" / "decisions"
        decisions_dir.mkdir(parents=True)

        active_file = decisions_dir / "0001-use-uv.md"
        active_file.write_text(
            "# 0001: Use UV\n\n* Status: accepted\n\n## Context\nFast builds.",
            encoding="utf-8",
        )

        deprecated_file = decisions_dir / "0002-use-poetry.md"
        deprecated_file.write_text(
            "# 0002: Use Poetry\n\n* Status: deprecated\n\n## Context\nLegacy.",
            encoding="utf-8",
        )

        proposed_file = decisions_dir / "0003-use-conda.md"
        proposed_file.write_text(
            "# 0003: Use Conda\n\n* Status: proposed\n\n## Context\nDraft.",
            encoding="utf-8",
        )

        seen_inodes: set[tuple[int, int]] = set()
        rules = scan_adr_rules(tmp_path, seen_inodes)

        assert len(rules) == 1
        assert "0001-use-uv.md" in rules[0].path
        assert "Use UV" in rules[0].content
        assert rules[0].source == "docs/decisions/0001-use-uv.md"

    def test_skips_when_no_adr_directory(self, tmp_path: Path) -> None:
        seen_inodes: set[tuple[int, int]] = set()
        rules = scan_adr_rules(tmp_path, seen_inodes)
        assert rules == []

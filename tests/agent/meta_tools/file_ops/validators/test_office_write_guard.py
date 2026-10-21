"""Tests for OfficeWriteGuard edge-case warnings."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.file_ops.validators.office_write_guard import (
    OfficeWriteGuard,
)


def test_office_write_guard_warns_on_docx_path() -> None:
    _content, warnings = OfficeWriteGuard.apply("/tmp/report.docx", "binary content")
    assert len(warnings) == 1
    assert "office" in warnings[0].lower()


def test_office_write_guard_ignores_markdown() -> None:
    _content, warnings = OfficeWriteGuard.apply("/tmp/readme.md", "# Title")
    assert warnings == []

"""Unit tests for cron delivery_guard.is_silent_output."""

from __future__ import annotations

from myrm_agent_harness.toolkits.cron.delivery_guard import is_silent_output


class TestIsSilentOutput:
    def test_exact_marker(self) -> None:
        assert is_silent_output("[SILENT]") is True

    def test_marker_with_whitespace(self) -> None:
        assert is_silent_output("  [SILENT]  ") is True

    def test_multiline_all_marker_lines(self) -> None:
        assert is_silent_output("[SILENT]\n[SILENT]") is True

    def test_markdown_fence_wrapped(self) -> None:
        assert is_silent_output("```\n[SILENT]\n```") is True

    def test_substantive_with_suffix_not_silent(self) -> None:
        assert is_silent_output("[SILENT] nothing to report") is False

    def test_substantive_content_not_silent(self) -> None:
        assert is_silent_output("CI failed on main branch") is False

    def test_empty_not_silent(self) -> None:
        assert is_silent_output("") is False
        assert is_silent_output(None) is False

    def test_marker_mention_in_prose_not_silent(self) -> None:
        assert is_silent_output("Use [SILENT] when there is nothing to report") is False

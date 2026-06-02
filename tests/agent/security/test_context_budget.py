"""Tests for ContextBudgetGuard including persist-to-disk functionality."""

from __future__ import annotations

import contextvars
from pathlib import Path
from unittest.mock import patch

from myrm_agent_harness.agent.security.guards.context_budget import (
    BudgetAction,
    ContextBudgetGuard,
    _resolve_persist_dir,
    get_context_budget_guard,
)


class TestBasicBudget:
    def test_ok_for_small_result(self) -> None:
        g = ContextBudgetGuard(max_result_chars=1000)
        v = g.check_and_truncate("x" * 500, "test_tool")
        assert v.action == BudgetAction.OK
        assert v.content == "x" * 500
        assert v.persisted_path is None

    def test_truncate_oversized_result(self) -> None:
        g = ContextBudgetGuard(max_result_chars=100)
        v = g.check_and_truncate("x" * 500, "test_tool")
        assert v.action == BudgetAction.TRUNCATED
        assert len(v.content) < 500
        assert "Truncated" in v.content
        assert v.persisted_path is None

    def test_warning_threshold(self) -> None:
        g = ContextBudgetGuard(max_result_chars=100_000, total_budget_tokens=100, warning_pct=0.80)
        g.check_and_truncate("x" * 400, "tool1")
        v = g.check_and_truncate("x" * 100, "tool2")
        assert v.action == BudgetAction.WARNING

    def test_predictive_overflow_truncation(self) -> None:
        g = ContextBudgetGuard(max_result_chars=100_000, total_budget_tokens=100, hard_limit_pct=0.95)
        g.check_and_truncate("x" * 360, "tool1")
        v = g.check_and_truncate("x" * 400, "tool2")
        assert v.action == BudgetAction.TRUNCATED

    def test_reset_clears_tokens(self) -> None:
        g = ContextBudgetGuard(total_budget_tokens=100)
        g.check_and_truncate("x" * 200, "tool1")
        assert g.used_tokens > 0
        g.reset()
        assert g.used_tokens == 0


class TestPersistToDisk:
    def test_persist_oversized_result(self, tmp_path: Path) -> None:
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        content = "line\n" * 200
        v = g.check_and_truncate(content, "file_read")
        assert v.action == BudgetAction.PERSISTED
        assert v.persisted_path is not None
        assert Path(v.persisted_path).exists()
        assert Path(v.persisted_path).read_text(encoding="utf-8") == content
        assert "FULL RESULT SAVED" in v.content
        assert "file_read" in v.persisted_path

    def test_persist_summary_contains_line_count(self, tmp_path: Path) -> None:
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        content = "line\n" * 50
        v = g.check_and_truncate(content, "grep")
        assert v.action == BudgetAction.PERSISTED
        assert "51 lines" in v.content

    def test_persist_summary_contains_file_path(self, tmp_path: Path) -> None:
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        v = g.check_and_truncate("x" * 500, "bash")
        assert v.action == BudgetAction.PERSISTED
        assert v.persisted_path is not None
        assert v.persisted_path in v.content

    def test_persist_summary_contains_head_preview(self, tmp_path: Path) -> None:
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        content = "HEADER_MARKER" + "x" * 500
        v = g.check_and_truncate(content, "tool")
        assert "HEADER_MARKER" in v.content

    def test_persist_reduces_budget_consumption(self, tmp_path: Path) -> None:
        g = ContextBudgetGuard(max_result_chars=100, total_budget_tokens=10_000, persist_dir=tmp_path)
        content = "x" * 50_000
        v = g.check_and_truncate(content, "big_tool")
        assert v.action == BudgetAction.PERSISTED
        assert g.used_tokens < 50_000 // 4

    def test_no_persist_when_under_limit(self, tmp_path: Path) -> None:
        g = ContextBudgetGuard(max_result_chars=1000, persist_dir=tmp_path)
        v = g.check_and_truncate("x" * 500, "tool")
        assert v.action == BudgetAction.OK
        assert v.persisted_path is None
        assert len(g.persisted_files) == 0

    def test_fallback_to_truncate_without_persist_dir(self) -> None:
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=None)
        v = g.check_and_truncate("x" * 500, "tool")
        assert v.action == BudgetAction.TRUNCATED
        assert v.persisted_path is None

    def test_reset_cleans_persisted_files(self, tmp_path: Path) -> None:
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        g.check_and_truncate("x" * 500, "tool1")
        g.check_and_truncate("y" * 500, "tool2")
        assert len(g.persisted_files) == 2
        files = g.persisted_files
        g.reset()
        assert len(g.persisted_files) == 0
        for f in files:
            assert not f.exists()

    def test_multiple_persists_unique_filenames(self, tmp_path: Path) -> None:
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        v1 = g.check_and_truncate("x" * 500, "file_read")
        v2 = g.check_and_truncate("y" * 500, "file_read")
        assert v1.persisted_path != v2.persisted_path

    def test_persist_skips_predictive_overflow(self, tmp_path: Path) -> None:
        """Persisted results skip Layer 3 predictive overflow (summary is small)."""
        g = ContextBudgetGuard(max_result_chars=100, total_budget_tokens=50, hard_limit_pct=0.95, persist_dir=tmp_path)
        g.check_and_truncate("x" * 160, "tool1")
        v = g.check_and_truncate("y" * 500, "tool2")
        assert v.action == BudgetAction.PERSISTED

    def test_persisted_files_property(self, tmp_path: Path) -> None:
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        g.check_and_truncate("x" * 500, "tool1")
        files = g.persisted_files
        assert len(files) == 1
        assert files[0].exists()

    def test_oserror_fallback_to_truncate(self, tmp_path: Path) -> None:
        """When disk write fails, gracefully fall back to truncation."""
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            v = g.check_and_truncate("x" * 500, "tool")
        assert v.action == BudgetAction.TRUNCATED
        assert v.persisted_path is None
        assert "Truncated" in v.content
        assert len(g.persisted_files) == 0


class TestLayer1Exemption:
    """Verify that file_read_tool and file_edit_tool bypass Layer 1 truncation."""

    def test_file_read_tool_exempt_from_truncation(self) -> None:
        g = ContextBudgetGuard(max_result_chars=100)
        content = "x" * 500
        v = g.check_and_truncate(content, "file_read_tool")
        assert v.action != BudgetAction.TRUNCATED or len(v.content) == len(content)
        assert v.action in (BudgetAction.OK, BudgetAction.WARNING)

    def test_file_edit_tool_exempt_from_truncation(self) -> None:
        g = ContextBudgetGuard(max_result_chars=100)
        content = "y" * 500
        v = g.check_and_truncate(content, "file_edit_tool")
        assert v.action in (BudgetAction.OK, BudgetAction.WARNING)
        assert v.content == content

    def test_file_read_exempt_even_with_persist_dir(self, tmp_path: Path) -> None:
        """file_read_tool is exempt even when persist_dir is configured."""
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        content = "z" * 500
        v = g.check_and_truncate(content, "file_read_tool")
        assert v.action != BudgetAction.PERSISTED
        assert v.persisted_path is None
        assert len(g.persisted_files) == 0

    def test_non_exempt_tool_gets_truncated(self) -> None:
        """Non-exempt tools ARE truncated at Layer 1."""
        g = ContextBudgetGuard(max_result_chars=100)
        content = "a" * 500
        v = g.check_and_truncate(content, "web_fetch_tool")
        assert v.action == BudgetAction.TRUNCATED
        assert len(v.content) < 500


class TestPersistContentReadability:
    """Verify persisted summaries contain info needed for Agent to re-read the file."""

    def test_persist_summary_has_file_path_for_reread(self, tmp_path: Path) -> None:
        """Agent must see a clear file path in the summary to re-read via file_read_tool."""
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        content = "important data\n" * 100
        v = g.check_and_truncate(content, "web_fetch_tool")
        assert v.action == BudgetAction.PERSISTED
        assert v.persisted_path is not None
        assert v.persisted_path in v.content
        assert "Read the file at the path above" in v.content

    def test_persist_summary_head_tail_preview(self, tmp_path: Path) -> None:
        """Summary should contain head and tail previews for context."""
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        head = "HEAD_MARKER_" + "x" * 50
        tail = "y" * 50 + "_TAIL_MARKER"
        content = head + "m" * 2000 + tail
        v = g.check_and_truncate(content, "http_tool")
        assert "HEAD_MARKER_" in v.content
        assert "_TAIL_MARKER" in v.content

    def test_persisted_file_contains_full_content(self, tmp_path: Path) -> None:
        """The persisted file must contain the full, unmodified content."""
        g = ContextBudgetGuard(max_result_chars=100, persist_dir=tmp_path)
        content = "line {}\n".format("x" * 100) * 50
        v = g.check_and_truncate(content, "mcp_tool")
        assert v.persisted_path is not None
        saved = Path(v.persisted_path).read_text(encoding="utf-8")
        assert saved == content


class TestCumulativeBudgetTracking:
    """Verify cumulative budget tracking across multiple tool calls."""

    def test_multiple_tools_accumulate_budget(self) -> None:
        g = ContextBudgetGuard(max_result_chars=100_000, total_budget_tokens=100, warning_pct=0.80)
        g.check_and_truncate("x" * 100, "tool1")
        g.check_and_truncate("y" * 100, "tool2")
        g.check_and_truncate("z" * 100, "tool3")
        assert g.used_tokens > 0
        assert g.budget_used_pct > 0

    def test_persisted_results_consume_less_budget(self, tmp_path: Path) -> None:
        """Persisted results consume far less budget than the original content."""
        g = ContextBudgetGuard(max_result_chars=100, total_budget_tokens=10_000, persist_dir=tmp_path)
        large_content = "x" * 50_000
        v = g.check_and_truncate(large_content, "big_tool")
        assert v.action == BudgetAction.PERSISTED
        tokens_after_persist = g.used_tokens
        assert tokens_after_persist < 50_000 // 4
        assert tokens_after_persist < 1000


class TestAutoResolvePersistDir:
    """Tests for automatic persist_dir resolution in get_context_budget_guard()."""

    def test_resolve_persist_dir_with_session_id(self) -> None:
        """When chat_id is set, persist_dir points to session evicted dir."""
        with patch(
            "myrm_agent_harness.agent.context_management.infra.session_lock.get_current_chat_id",
            return_value="test_session_123",
        ):
            result = _resolve_persist_dir()
        assert result is not None
        assert "test_session_123" in str(result)
        assert "evicted" in str(result)

    def test_resolve_persist_dir_without_session_id(self) -> None:
        """When no chat_id, falls back to temp directory."""
        with patch(
            "myrm_agent_harness.agent.context_management.infra.session_lock.get_current_chat_id", return_value=None
        ):
            result = _resolve_persist_dir()
        assert result is not None
        assert "myrm-budget-persist" in str(result)

    def test_resolve_persist_dir_sanitizes_chat_id(self) -> None:
        """Special characters in chat_id are sanitized."""
        with patch(
            "myrm_agent_harness.agent.context_management.infra.session_lock.get_current_chat_id",
            return_value="chat/../../etc/passwd",
        ):
            result = _resolve_persist_dir()
        assert result is not None
        path_str = str(result)
        assert "/../" not in path_str

    def test_resolve_persist_dir_handles_exception(self) -> None:
        """When imports fail, returns None gracefully."""
        with patch(
            "myrm_agent_harness.agent.context_management.infra.session_lock.get_current_chat_id",
            side_effect=RuntimeError("unexpected error"),
        ):
            result = _resolve_persist_dir()
        assert result is None

    def test_get_guard_creates_with_persist_dir(self) -> None:
        """get_context_budget_guard() creates guard with persist_dir when session exists."""
        ctx = contextvars.copy_context()

        def _run_in_clean_context() -> Path | None:
            with patch(
                "myrm_agent_harness.agent.security.guards.context_budget._resolve_persist_dir",
                return_value=Path("/tmp/test-persist"),
            ):
                guard = get_context_budget_guard()
                return guard._persist_dir

        result = ctx.run(_run_in_clean_context)
        assert result == Path("/tmp/test-persist")

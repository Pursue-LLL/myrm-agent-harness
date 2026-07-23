"""Tests for ContextBudgetGuard including UECD persist-to-disk functionality."""

from __future__ import annotations

import contextvars
from pathlib import Path

import pytest

from myrm_agent_harness.agent.security.guards.context_budget import (
    BudgetAction,
    ContextBudgetGuard,
    get_context_budget_guard,
)
from myrm_agent_harness.core.context_vars import chat_id_var, workspace_root_var


@pytest.fixture
def uecd_session(tmp_path: Path) -> tuple[str, str]:
    """Bind workspace + chat context required by UECD persist."""
    workspace = str(tmp_path)
    chat_id = "budget_test_chat"
    w_tok = workspace_root_var.set(workspace)
    c_tok = chat_id_var.set(chat_id)
    try:
        yield workspace, chat_id
    finally:
        workspace_root_var.reset(w_tok)
        chat_id_var.reset(c_tok)


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
    def test_persist_oversized_result(self, uecd_session: tuple[str, str]) -> None:
        workspace, _chat_id = uecd_session
        g = ContextBudgetGuard(max_result_chars=100)
        content = "line\n" * 200
        v = g.check_and_truncate(content, "grep_tool")
        assert v.action == BudgetAction.PERSISTED
        assert v.persisted_path is not None
        assert v.evicted_ref is not None
        saved = Path(workspace) / v.persisted_path
        assert saved.is_file()
        assert saved.read_text(encoding="utf-8") == content
        assert "Full content saved to sandbox storage" in v.content

    def test_persist_summary_contains_line_count(self, uecd_session: tuple[str, str]) -> None:
        g = ContextBudgetGuard(max_result_chars=100)
        content = "line\n" * 300
        v = g.check_and_truncate(content, "grep")
        assert v.action == BudgetAction.PERSISTED
        assert "lines total" in v.content

    def test_persist_summary_contains_file_path(self, uecd_session: tuple[str, str]) -> None:
        g = ContextBudgetGuard(max_result_chars=100)
        v = g.check_and_truncate("x" * 500, "bash")
        assert v.action == BudgetAction.PERSISTED
        assert v.persisted_path is not None
        assert v.persisted_path in v.content

    def test_persist_reduces_budget_consumption(self, uecd_session: tuple[str, str]) -> None:
        g = ContextBudgetGuard(max_result_chars=100, total_budget_tokens=10_000)
        content = "x" * 50_000
        v = g.check_and_truncate(content, "big_tool")
        assert v.action == BudgetAction.PERSISTED
        assert g.used_tokens < 50_000 // 4

    def test_no_persist_when_under_limit(self, uecd_session: tuple[str, str]) -> None:
        g = ContextBudgetGuard(max_result_chars=1000)
        v = g.check_and_truncate("x" * 500, "tool")
        assert v.action == BudgetAction.OK
        assert v.persisted_path is None

    def test_fallback_to_truncate_without_session_context(self) -> None:
        g = ContextBudgetGuard(max_result_chars=100)
        v = g.check_and_truncate("x" * 500, "tool")
        assert v.action == BudgetAction.TRUNCATED
        assert v.persisted_path is None

    def test_multiple_persists_unique_filenames(self, uecd_session: tuple[str, str]) -> None:
        g = ContextBudgetGuard(max_result_chars=100)
        v1 = g.check_and_truncate("x" * 500, "http_tool")
        v2 = g.check_and_truncate("y" * 500, "http_tool")
        assert v1.persisted_path != v2.persisted_path

    def test_persist_skips_predictive_overflow(self, uecd_session: tuple[str, str]) -> None:
        """Persisted results skip Layer 3 predictive overflow (summary is small)."""
        g = ContextBudgetGuard(max_result_chars=100, total_budget_tokens=50, hard_limit_pct=0.95)
        g.check_and_truncate("x" * 160, "tool1")
        v = g.check_and_truncate("y" * 500, "tool2")
        assert v.action == BudgetAction.PERSISTED

    def test_oserror_fallback_to_truncate(self, uecd_session: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
        """When UECD disk write fails, gracefully fall back to truncation."""
        g = ContextBudgetGuard(max_result_chars=100)

        def _fail_write(*_args: object, **_kwargs: object) -> object:
            from myrm_agent_harness.agent.context_management.infra.evicted_content import EvictedPersistResult

            return EvictedPersistResult(evicted_ref=None, rel_path=None, stored_chars=0)

        monkeypatch.setattr(
            "myrm_agent_harness.agent.context_management.infra.evicted_content.write_evicted_content_sync",
            _fail_write,
        )
        v = g.check_and_truncate("x" * 500, "tool")
        assert v.action == BudgetAction.TRUNCATED
        assert v.persisted_path is None
        assert "Truncated" in v.content


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

    def test_file_read_exempt_even_with_session(self, uecd_session: tuple[str, str]) -> None:
        g = ContextBudgetGuard(max_result_chars=100)
        content = "z" * 500
        v = g.check_and_truncate(content, "file_read_tool")
        assert v.action != BudgetAction.PERSISTED
        assert v.persisted_path is None

    def test_non_exempt_tool_gets_truncated_without_session(self) -> None:
        g = ContextBudgetGuard(max_result_chars=100)
        content = "a" * 500
        v = g.check_and_truncate(content, "web_fetch_tool")
        assert v.action == BudgetAction.TRUNCATED
        assert len(v.content) < 500


class TestPersistContentReadability:
    """Verify persisted summaries contain info needed for Agent to re-read the file."""

    def test_persist_summary_has_file_path_for_reread(self, uecd_session: tuple[str, str]) -> None:
        g = ContextBudgetGuard(max_result_chars=100)
        content = "important data\n" * 100
        v = g.check_and_truncate(content, "web_fetch_tool")
        assert v.action == BudgetAction.PERSISTED
        assert v.persisted_path is not None
        assert v.persisted_path in v.content
        assert "file_read_tool" in v.content

    def test_persist_summary_head_tail_preview(self, uecd_session: tuple[str, str]) -> None:
        head = "HEAD_MARKER_" + "x" * 50
        tail = "y" * 50 + "_TAIL_MARKER"
        content = head + "m" * 2000 + tail
        g = ContextBudgetGuard(max_result_chars=100)
        v = g.check_and_truncate(content, "http_tool")
        assert "HEAD_MARKER_" in v.content
        assert "_TAIL_MARKER" in v.content

    def test_persisted_file_contains_full_content(self, uecd_session: tuple[str, str]) -> None:
        workspace, _chat_id = uecd_session
        g = ContextBudgetGuard(max_result_chars=100)
        content = "line {}\n".format("x" * 100) * 50
        v = g.check_and_truncate(content, "mcp_tool")
        assert v.persisted_path is not None
        saved = Path(workspace) / v.persisted_path
        assert saved.read_text(encoding="utf-8") == content


class TestCumulativeBudgetTracking:
    def test_multiple_tools_accumulate_budget(self) -> None:
        g = ContextBudgetGuard(max_result_chars=100_000, total_budget_tokens=100, warning_pct=0.80)
        g.check_and_truncate("x" * 100, "tool1")
        g.check_and_truncate("y" * 100, "tool2")
        g.check_and_truncate("z" * 100, "tool3")
        assert g.used_tokens > 0
        assert g.budget_used_pct > 0

    def test_persisted_results_consume_less_budget(self, uecd_session: tuple[str, str]) -> None:
        g = ContextBudgetGuard(max_result_chars=100, total_budget_tokens=10_000)
        large_content = "x" * 50_000
        v = g.check_and_truncate(large_content, "big_tool")
        assert v.action == BudgetAction.PERSISTED
        tokens_after_persist = g.used_tokens
        assert tokens_after_persist < 50_000 // 4
        assert tokens_after_persist < 1000


class TestGetContextBudgetGuard:
    def test_get_guard_creates_default_instance(self) -> None:
        ctx = contextvars.copy_context()

        def _run_in_clean_context() -> ContextBudgetGuard:
            return get_context_budget_guard()

        guard = ctx.run(_run_in_clean_context)
        assert isinstance(guard, ContextBudgetGuard)
        v = guard.check_and_truncate("x" * 50, "probe")
        assert v.action == BudgetAction.OK

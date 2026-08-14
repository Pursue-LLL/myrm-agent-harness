"""Unit tests for navigation interactive summary and extraction vault spill thresholds.

Strictly unit level: mocks BrowserSession components to verify adaptive limits
and vault overflow behaviors without launching real browsers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from myrm_agent_harness.toolkits.browser.session.browser_session_navigation_mixin import (
    _NAVIGATE_INTERACTIVE_SUMMARY_MAX_LINES,
    _NAVIGATE_INTERACTIVE_SUMMARY_MAX_TOKENS,
    BrowserSessionNavigationMixin,
)
from myrm_agent_harness.toolkits.browser.session.browser_session_extraction_mixin import (
    _DEFAULT_VAULT_SPILL_CHAR_THRESHOLD,
    BrowserSessionExtractionMixin,
)
from myrm_agent_harness.toolkits.browser.session.snapshot_result import SnapshotResult


class _DummyNavSession(BrowserSessionNavigationMixin):
    def __init__(self, aria_tree: str):
        self._aria_tree = aria_tree
        self.snapshot_calls = []

    async def snapshot(self, **kwargs) -> SnapshotResult:
        self.snapshot_calls.append(kwargs)
        from types import MappingProxyType
        from myrm_agent_harness.toolkits.browser.snapshot import SnapshotMeta
        return SnapshotResult(
            aria_tree=self._aria_tree,
            refs=MappingProxyType({}),
            meta=SnapshotMeta(ref_count=0, estimated_tokens=10),
            is_incremental=False,
        )


class _DummyExtractSession(BrowserSessionExtractionMixin):
    def __init__(self, full_text: str, vault_mock=None):
        self._ensure_components = AsyncMock()
        self._extractor = MagicMock()
        self._extractor.extract_full_text = AsyncMock(return_value=full_text)
        self._tab_controller = MagicMock()
        self._tab_controller.get_active_tab_id.return_value = "tab-1"
        self._tab_controller.get_text_snapshot.return_value = None
        active_page = MagicMock()
        active_page.url = "https://example.com/long-page"
        self._tab_controller.get_active_page.return_value = active_page
        self._vision_llm = None
        self._content_vault = vault_mock

    def _require_extractor(self):
        return self._extractor


@pytest.mark.asyncio
async def test_navigation_interactive_summary_budget_and_lines():
    """Verify adaptive summary uses 1500 tokens budget and caps at 100 lines."""
    assert _NAVIGATE_INTERACTIVE_SUMMARY_MAX_TOKENS == 1500
    assert _NAVIGATE_INTERACTIVE_SUMMARY_MAX_LINES == 100

    # 120 lines of interactive refs
    many_lines = "\n".join([f"- [ref=e{i}] Button {i}" for i in range(120)])
    session = _DummyNavSession(many_lines)

    res = await session._append_navigate_interactive_summary("Navigated to https://example.com")

    # Checked that max_tokens was passed to snapshot
    assert len(session.snapshot_calls) == 1
    assert session.snapshot_calls[0]["max_tokens"] == 1500
    assert session.snapshot_calls[0]["scope"] == "interactive"
    assert session.snapshot_calls[0]["compact"] is True

    # Check that output contains first 100 lines and truncation note
    assert "- [ref=e0] Button 0" in res
    assert "- [ref=e99] Button 99" in res
    assert "- [ref=e100] Button 100" not in res
    assert "... (20 more refs; use browser_snapshot for full tree)" in res


@pytest.mark.asyncio
async def test_extraction_vault_spill_threshold():
    """Verify content > 30000 chars is offloaded to ContentVault."""
    assert _DEFAULT_VAULT_SPILL_CHAR_THRESHOLD == 30000

    vault = MagicMock()
    vault.put.return_value = "vault://session-123/extracted.md"

    # 35,000 chars (over threshold)
    large_text = "A" * 35000
    session = _DummyExtractSession(large_text, vault_mock=vault)

    result = await session.extract_text(resume_cursor=0, max_length=20000)

    # ContentVault must be called
    vault.put.assert_called_once()
    assert "Vault URI: vault://session-123/extracted.md" in result
    assert "Page content is extremely long (35000 chars)" in result


@pytest.mark.asyncio
async def test_extraction_under_threshold_no_vault():
    """Verify content under threshold does standard pagination without vault."""
    vault = MagicMock()

    # 25,000 chars (under 30,000 threshold but over max_length 20,000)
    medium_text = "B" * 25000
    session = _DummyExtractSession(medium_text, vault_mock=vault)

    result = await session.extract_text(resume_cursor=0, max_length=20000)

    # Vault not triggered
    vault.put.assert_not_called()
    assert "Vault URI" not in result
    assert "5000 chars remaining" in result

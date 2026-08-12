"""Redaction guarantees for the browser exception hierarchy.

Covers credential masking at construction (str(e) is the propagation path to the
LLM) and in format_for_llm(), plus the RefNotFoundError URL-change suggestion
that previously surfaced full query strings.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.browser.exceptions import (
    BrowserError,
    RefNotFoundError,
)


class TestBrowserErrorRedaction:
    def test_message_credential_redacted_at_construction(self) -> None:
        err = BrowserError(
            "Navigation failed for https://app.com/callback?code=4d3f9c2a1b8e"
        )
        assert "4d3f9c2a1b8e" not in str(err)
        assert "code=***" in str(err)

    def test_plain_message_unchanged(self) -> None:
        err = BrowserError("Element not found in snapshot")
        assert str(err) == "Element not found in snapshot"

    def test_format_for_llm_redacts_context_and_diagnostics(self) -> None:
        err = BrowserError(
            "Request failed",
            context={"url": "https://app.com/callback?code=9f8e7d6c5b4a"},
            diagnostic_info={"token": "sk-proj-abcdef123456"},
            recovery_suggestions=["verify token sk-proj-abcdef123456"],
        )
        out = err.format_for_llm()
        assert "9f8e7d6c5b4a" not in out
        assert "sk-proj-abcdef123456" not in out
        assert "Request failed" in out

    def test_format_for_llm_preserves_plain_content(self) -> None:
        err = BrowserError("Timeout after 30s", error_code="NAV_TIMEOUT")
        out = err.format_for_llm()
        assert "Timeout after 30s" in out
        assert "NAV_TIMEOUT" in out


class TestRefNotFoundErrorRedaction:
    def _build(self, current_url: str, last_url: str) -> RefNotFoundError:
        return RefNotFoundError(
            ref="e999",
            total_refs=5,
            ref_range="e0-e4",
            context_refs=[{"ref": "e0", "role": "button", "name": "Submit"}],
            last_snapshot_url=last_url,
            context={"page_url": current_url},
        )

    def test_query_credential_never_surfaces_in_message(self) -> None:
        last_url = "https://app.com/checkout"
        current_url = "https://app.com/callback?code=4d3f9c2a1b8e7f6d"
        err = self._build(current_url, last_url)
        assert "4d3f9c2a1b8e7f6d" not in str(err)
        assert "Page has navigated from" in str(err)

    def test_query_credential_redacted_in_query_change_message(self) -> None:
        last_url = "https://app.com/checkout"
        current_url = "https://app.com/checkout?code=4d3f9c2a1b8e7f6d"
        err = self._build(current_url, last_url)
        assert "4d3f9c2a1b8e7f6d" not in str(err)
        assert "code=***" in str(err)

    def test_query_change_message_redacted(self) -> None:
        last_url = "https://app.com/checkout"
        current_url = "https://app.com/checkout?session=abc123xyz789"
        err = self._build(current_url, last_url)
        assert "abc123xyz789" not in str(err)
        assert "Query params changed" in str(err)

    def test_plain_navigation_kept_readable(self) -> None:
        err = self._build(
            "https://app.com/settings",
            "https://app.com/checkout",
        )
        msg = str(err)
        assert "Page has navigated from" in msg
        assert "app.com" in msg

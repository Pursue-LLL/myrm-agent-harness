"""Unit tests for context_factory._sync_accept_language.

Validates that Accept-Language headers are correctly derived from locale
settings and that module-level constants are never mutated (shallow copy safety).
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.pool.context_factory import (
    _DEFAULT_CONTEXT_OPTIONS,
    _sync_accept_language,
)


class TestSyncAcceptLanguage:
    """Tests for _sync_accept_language header alignment."""

    def test_region_locale_produces_two_values(self) -> None:
        ctx: dict[str, object] = {"extra_http_headers": {"Accept-Language": "old"}}
        _sync_accept_language(ctx, "ja-JP")
        headers = ctx["extra_http_headers"]
        assert isinstance(headers, dict)
        assert headers["Accept-Language"] == "ja-JP,ja;q=0.9"

    def test_bare_language_locale(self) -> None:
        ctx: dict[str, object] = {"extra_http_headers": {"Accept-Language": "old"}}
        _sync_accept_language(ctx, "en")
        headers = ctx["extra_http_headers"]
        assert isinstance(headers, dict)
        assert headers["Accept-Language"] == "en;q=1"

    def test_no_headers_key_is_noop(self) -> None:
        ctx: dict[str, object] = {"viewport": {"width": 1920}}
        _sync_accept_language(ctx, "ja-JP")
        assert "extra_http_headers" not in ctx

    def test_headers_not_dict_is_noop(self) -> None:
        ctx: dict[str, object] = {"extra_http_headers": "invalid"}
        _sync_accept_language(ctx, "ja-JP")
        assert ctx["extra_http_headers"] == "invalid"

    def test_does_not_mutate_module_constant(self) -> None:
        original_lang = None
        orig_headers = _DEFAULT_CONTEXT_OPTIONS.get("extra_http_headers")
        if isinstance(orig_headers, dict):
            original_lang = orig_headers.get("Accept-Language")

        ctx = dict(_DEFAULT_CONTEXT_OPTIONS)
        _sync_accept_language(ctx, "fr-FR")

        current_headers = _DEFAULT_CONTEXT_OPTIONS.get("extra_http_headers")
        assert isinstance(current_headers, dict)
        assert current_headers.get("Accept-Language") == original_lang

    def test_other_headers_preserved(self) -> None:
        ctx: dict[str, object] = {
            "extra_http_headers": {
                "Accept": "text/html",
                "Accept-Language": "old",
                "DNT": "1",
            }
        }
        _sync_accept_language(ctx, "de-DE")
        headers = ctx["extra_http_headers"]
        assert isinstance(headers, dict)
        assert headers["Accept"] == "text/html"
        assert headers["DNT"] == "1"
        assert headers["Accept-Language"] == "de-DE,de;q=0.9"

    @pytest.mark.parametrize(
        ("locale", "expected"),
        [
            ("zh-CN", "zh-CN,zh;q=0.9"),
            ("en-US", "en-US,en;q=0.9"),
            ("ko-KR", "ko-KR,ko;q=0.9"),
            ("pt-BR", "pt-BR,pt;q=0.9"),
        ],
    )
    def test_common_locales(self, locale: str, expected: str) -> None:
        ctx: dict[str, object] = {"extra_http_headers": {"Accept-Language": "old"}}
        _sync_accept_language(ctx, locale)
        headers = ctx["extra_http_headers"]
        assert isinstance(headers, dict)
        assert headers["Accept-Language"] == expected

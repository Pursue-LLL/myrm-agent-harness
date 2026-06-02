"""Tests for page-level CAPTCHA detector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.captcha.detector import (
    _BLOCKING_CAPTCHA_PATTERNS,
    _SHORT_PAGE_CAPTCHA_PATTERNS,
    detect_captcha,
)
from myrm_agent_harness.toolkits.browser.captcha.protocols import CaptchaType


def _make_page(html: str) -> MagicMock:
    """Create a mock Patchright Page with given HTML content."""
    page = MagicMock()
    page.content = AsyncMock(return_value=html)
    return page


class TestDetectCaptcha:
    """detect_captcha function tests."""

    @pytest.mark.asyncio
    async def test_clean_page_returns_none(self) -> None:
        page = _make_page("<html><body><h1>Hello World</h1></body></html>")
        result = await detect_captcha(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_cloudflare_challenge_form(self) -> None:
        html = '<form id="challenge-form" action="/challenge" method="POST"><input name="__cf_chl_f_tk=" value="abc"></form>'
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.CLOUDFLARE_CHALLENGE
        assert result.confidence == 1.0
        assert result.blocking is True

    @pytest.mark.asyncio
    async def test_cloudflare_js_challenge(self) -> None:
        html = '<script src="/cdn-cgi/challenge-platform/scripts/turnstile/orchestrate"></script>'
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.CLOUDFLARE_CHALLENGE

    @pytest.mark.asyncio
    async def test_cloudflare_turnstile_iframe(self) -> None:
        html = '<iframe src="https://challenges.cloudflare.com/turnstile/v0/abc123"></iframe>'
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.CLOUDFLARE_TURNSTILE

    @pytest.mark.asyncio
    async def test_cloudflare_turnstile_widget(self) -> None:
        html = '<div class="cf-turnstile" data-sitekey="xxx"></div>'
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.CLOUDFLARE_TURNSTILE

    @pytest.mark.asyncio
    async def test_perimeterx_captcha(self) -> None:
        html = '<script src="https://captcha.px-cdn.net/abc/captcha.js"></script>'
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.PERIMETERX

    @pytest.mark.asyncio
    async def test_datadome_captcha(self) -> None:
        html = '<iframe src="https://geo.captcha-delivery.com/captcha/"></iframe>'
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.DATADOME

    @pytest.mark.asyncio
    async def test_kasada_challenge(self) -> None:
        html = "<script>KPSDK.scriptStart = KPSDK.now()</script>"
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.KASADA

    @pytest.mark.asyncio
    async def test_akamai_challenge(self) -> None:
        html = "<html><body><h1>Pardon Our Interruption</h1></body></html>"
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.AKAMAI

    @pytest.mark.asyncio
    async def test_imperva_block(self) -> None:
        html = '<script src="/_Incapsula_Resource?abc=123"></script>'
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.IMPERVA

    @pytest.mark.asyncio
    async def test_short_page_recaptcha(self) -> None:
        html = '<html><body><div class="g-recaptcha" data-sitekey="xxx"></div></body></html>'
        assert len(html) < 10_000
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.RECAPTCHA
        assert result.confidence == 0.8

    @pytest.mark.asyncio
    async def test_long_page_recaptcha_ignored(self) -> None:
        """reCAPTCHA on large page is treated as embedded widget, not blocking."""
        html = '<html><body>' + 'x' * 15_000 + '<div class="g-recaptcha" data-sitekey="xxx"></div></body></html>'
        assert len(html) > 10_000
        result = await detect_captcha(_make_page(html))
        assert result is None

    @pytest.mark.asyncio
    async def test_short_page_hcaptcha(self) -> None:
        html = '<html><body><div class="h-captcha" data-sitekey="xxx"></div></body></html>'
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.HCAPTCHA

    @pytest.mark.asyncio
    async def test_checking_your_browser_short_page(self) -> None:
        html = "<html><body>Checking your browser before accessing...</body></html>"
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.CLOUDFLARE_CHALLENGE

    @pytest.mark.asyncio
    async def test_just_a_moment_interstitial(self) -> None:
        html = "<html><head><title>Just a moment...</title></head><body></body></html>"
        result = await detect_captcha(_make_page(html))
        assert result is not None
        assert result.captcha_type == CaptchaType.CLOUDFLARE_CHALLENGE

    @pytest.mark.asyncio
    async def test_page_content_exception_returns_none(self) -> None:
        page = MagicMock()
        page.content = AsyncMock(side_effect=RuntimeError("Connection closed"))
        result = await detect_captcha(page)
        assert result is None


class TestPatternCompleteness:
    """Verify pattern lists are not empty and well-structured."""

    def test_blocking_patterns_not_empty(self) -> None:
        assert len(_BLOCKING_CAPTCHA_PATTERNS) >= 8

    def test_short_page_patterns_not_empty(self) -> None:
        assert len(_SHORT_PAGE_CAPTCHA_PATTERNS) >= 4

    def test_all_patterns_have_three_elements(self) -> None:
        for pattern, reason, captcha_type in _BLOCKING_CAPTCHA_PATTERNS:
            assert hasattr(pattern, "search")
            assert isinstance(reason, str)
            assert isinstance(captcha_type, CaptchaType)
        for pattern, reason, captcha_type in _SHORT_PAGE_CAPTCHA_PATTERNS:
            assert hasattr(pattern, "search")
            assert isinstance(reason, str)
            assert isinstance(captcha_type, CaptchaType)

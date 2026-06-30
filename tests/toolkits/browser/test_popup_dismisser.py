"""Unit tests for ConsentDismisser component and Navigator integration.

Tests the multi-phase cookie consent dismissal: CMP-specific clicks, generic
selectors, multilingual text matching, Shadow DOM, CMP JS APIs, and container
removal. Also verifies fail-safe behavior, config toggle, and Navigator integration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.session.consent_dismisser import (
    ConsentDismisser,
    _DISMISS_CONSENT_JS,
)


def _make_page(evaluate_return: dict | None = None, evaluate_side_effect: Exception | None = None) -> MagicMock:
    """Create a mock Page with evaluate support."""
    page = MagicMock()
    if evaluate_side_effect:
        page.evaluate = AsyncMock(side_effect=evaluate_side_effect)
    else:
        page.evaluate = AsyncMock(return_value=evaluate_return)
    return page


# =============================================================================
# ConsentDismisser core behavior
# =============================================================================


@pytest.mark.asyncio
async def test_dismisser_returns_description_on_success():
    page = _make_page({"dismissed": True, "method": "cmp_selector"})
    dismisser = ConsentDismisser(enabled=True)
    result = await dismisser.dismiss(page)
    assert result is not None
    assert "cmp_selector" in result


@pytest.mark.asyncio
async def test_dismisser_returns_none_when_no_popup():
    page = _make_page({"dismissed": False, "method": None})
    dismisser = ConsentDismisser(enabled=True)
    result = await dismisser.dismiss(page)
    assert result is None


@pytest.mark.asyncio
async def test_dismisser_returns_none_when_disabled():
    page = _make_page({"dismissed": True, "method": "cmp_selector"})
    dismisser = ConsentDismisser(enabled=False)
    result = await dismisser.dismiss(page)
    assert result is None
    page.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_dismisser_handles_exception_gracefully():
    page = _make_page(evaluate_side_effect=RuntimeError("page crashed"))
    dismisser = ConsentDismisser(enabled=True)
    result = await dismisser.dismiss(page)
    assert result is None


@pytest.mark.asyncio
async def test_dismisser_handles_none_result():
    page = _make_page(None)
    dismisser = ConsentDismisser(enabled=True)
    result = await dismisser.dismiss(page)
    assert result is None


# =============================================================================
# Enabled/disabled toggle
# =============================================================================


def test_default_enabled():
    d = ConsentDismisser()
    assert d.enabled is True


def test_explicit_disable():
    d = ConsentDismisser(enabled=False)
    assert d.enabled is False


def test_property_setter():
    d = ConsentDismisser(enabled=True)
    d.enabled = False
    assert d.enabled is False


# =============================================================================
# Methods returned
# =============================================================================


@pytest.mark.asyncio
async def test_generic_selector_method():
    page = _make_page({"dismissed": True, "method": "generic_selector"})
    result = await ConsentDismisser().dismiss(page)
    assert "generic_selector" in result


@pytest.mark.asyncio
async def test_text_match_method():
    page = _make_page({"dismissed": True, "method": "text_match"})
    result = await ConsentDismisser().dismiss(page)
    assert "text_match" in result


@pytest.mark.asyncio
async def test_shadow_dom_method():
    page = _make_page({"dismissed": True, "method": "shadow_dom"})
    result = await ConsentDismisser().dismiss(page)
    assert "shadow_dom" in result


@pytest.mark.asyncio
async def test_didomi_api_method():
    page = _make_page({"dismissed": True, "method": "didomi_api"})
    result = await ConsentDismisser().dismiss(page)
    assert "didomi_api" in result


@pytest.mark.asyncio
async def test_container_removal_method():
    page = _make_page({"dismissed": True, "method": "container_removal"})
    result = await ConsentDismisser().dismiss(page)
    assert "container_removal" in result


# =============================================================================
# JS snippet structural checks
# =============================================================================


def test_js_has_cmp_specific_selectors():
    assert "#onetrust-accept-btn-handler" in _DISMISS_CONSENT_JS
    assert "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll" in _DISMISS_CONSENT_JS
    assert "#didomi-notice-agree-button" in _DISMISS_CONSENT_JS


def test_js_has_generic_selectors():
    assert 'button[id*="accept" i]' in _DISMISS_CONSENT_JS
    assert 'button[class*="accept-all" i]' in _DISMISS_CONSENT_JS


def test_js_has_multilingual_text_patterns():
    assert "alle\\s*akzeptieren" in _DISMISS_CONSENT_JS
    assert "tout\\s*accepter" in _DISMISS_CONSENT_JS
    assert "全部接受" in _DISMISS_CONSENT_JS


def test_js_has_shadow_dom_support():
    assert "shadowRoot" in _DISMISS_CONSENT_JS
    assert "usercentrics-root" in _DISMISS_CONSENT_JS


def test_js_has_cmp_api_calls():
    assert "__tcfapi" in _DISMISS_CONSENT_JS
    assert "Didomi" in _DISMISS_CONSENT_JS
    assert "Cookiebot" in _DISMISS_CONSENT_JS


def test_js_has_container_removal_phase():
    assert "#onetrust-consent-sdk" in _DISMISS_CONSENT_JS
    assert "#CybotCookiebotDialog" in _DISMISS_CONSENT_JS
    assert "container_removal" in _DISMISS_CONSENT_JS


def test_js_has_iframe_removal():
    assert 'iframe[id^="sp_message_iframe"]' in _DISMISS_CONSENT_JS
    assert 'iframe[src*="consent" i]' in _DISMISS_CONSENT_JS


def test_js_has_scroll_restoration():
    assert "overflow" in _DISMISS_CONSENT_JS
    assert "ot-overflow-hidden" in _DISMISS_CONSENT_JS


def test_js_has_extra_cmp_selectors():
    assert "#catapultCookie" in _DISMISS_CONSENT_JS
    assert "#adopt-accept-all-button" in _DISMISS_CONSENT_JS
    assert "#kc-acceptAndHide" in _DISMISS_CONSENT_JS


# =============================================================================
# Navigator integration — config toggle
# =============================================================================


@pytest.mark.asyncio
async def test_navigator_skips_dismiss_when_disabled():
    from myrm_agent_harness.toolkits.browser.navigation import Navigator

    mock_req = MagicMock(url="https://example.com", redirected_from=None)
    mock_resp = MagicMock(status=200, request=mock_req)

    page = MagicMock()
    page.goto = AsyncMock(return_value=mock_resp)
    page.title = AsyncMock(return_value="Test")
    page.url = "https://example.com"
    page.route = AsyncMock()
    page.unroute = AsyncMock()
    page.main_frame = MagicMock()

    nav = Navigator(page, auto_dismiss_popups=False)

    with patch("myrm_agent_harness.toolkits.browser.navigation.wait_for_page_ready") as mock_wait:
        mock_wait.return_value = MagicMock(
            reason="both", elapsed_ms=100, dom_stable_ms=50, network_idle_ms=50,
            dom_mutation_count=0, dom_reset_count=0, to_log_dict=lambda: {},
        )
        with patch(
            "myrm_agent_harness.toolkits.browser.session.consent_dismisser.ConsentDismisser.dismiss"
        ) as mock_dismiss:
            await nav.goto("https://example.com")
            mock_dismiss.assert_not_called()


@pytest.mark.asyncio
async def test_navigator_calls_dismiss_when_enabled():
    from myrm_agent_harness.toolkits.browser.navigation import Navigator

    mock_req = MagicMock(url="https://example.com", redirected_from=None)
    mock_resp = MagicMock(status=200, request=mock_req)

    page = MagicMock()
    page.goto = AsyncMock(return_value=mock_resp)
    page.title = AsyncMock(return_value="Test")
    page.url = "https://example.com"
    page.route = AsyncMock()
    page.unroute = AsyncMock()
    page.main_frame = MagicMock()

    nav = Navigator(page, auto_dismiss_popups=True)

    with patch("myrm_agent_harness.toolkits.browser.navigation.wait_for_page_ready") as mock_wait:
        mock_wait.return_value = MagicMock(
            reason="both", elapsed_ms=100, dom_stable_ms=50, network_idle_ms=50,
            dom_mutation_count=0, dom_reset_count=0, to_log_dict=lambda: {},
        )
        with patch(
            "myrm_agent_harness.toolkits.browser.session.consent_dismisser.ConsentDismisser.dismiss",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_dismiss:
            await nav.goto("https://example.com")
            mock_dismiss.assert_awaited_once()


# =============================================================================
# BrowserConfig integration
# =============================================================================


def test_browser_config_default_auto_dismiss():
    from myrm_agent_harness.toolkits.browser.pool.config import BrowserConfig

    config = BrowserConfig()
    assert config.auto_dismiss_popups is True


def test_browser_config_disable_auto_dismiss():
    from myrm_agent_harness.toolkits.browser.pool.config import BrowserConfig

    config = BrowserConfig(auto_dismiss_popups=False)
    assert config.auto_dismiss_popups is False

"""Unit tests for GlobalBrowserPool.is_managed_for_page (takeover routing)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool import BrowserInstance, GlobalBrowserPool


@pytest.fixture
def pool() -> GlobalBrowserPool:
    return GlobalBrowserPool(max_browsers=2)


def _make_page(*, browser: object | None, context_error: bool = False) -> MagicMock:
    page = MagicMock()
    if context_error:
        type(page).context = property(lambda self: (_ for _ in ()).throw(RuntimeError("no context")))
    else:
        context = MagicMock()
        context.browser = browser
        page.context = context
    return page


def test_is_managed_for_page_returns_instance_flag(pool: GlobalBrowserPool) -> None:
    browser = MagicMock()
    page = _make_page(browser=browser)
    pool._browsers.append(BrowserInstance(browser=browser, engine="chromium", is_managed=True))

    assert pool.is_managed_for_page(page) is True


def test_is_managed_for_page_returns_false_for_external_browser(pool: GlobalBrowserPool) -> None:
    browser = MagicMock()
    page = _make_page(browser=browser)
    pool._browsers.append(BrowserInstance(browser=browser, engine="chromium", is_managed=False))

    assert pool.is_managed_for_page(page) is False


def test_is_managed_for_page_defaults_true_when_browser_unknown(pool: GlobalBrowserPool) -> None:
    page = _make_page(browser=MagicMock())

    assert pool.is_managed_for_page(page) is True


def test_is_managed_for_page_defaults_true_on_context_error(pool: GlobalBrowserPool) -> None:
    page = _make_page(browser=None, context_error=True)

    assert pool.is_managed_for_page(page) is True

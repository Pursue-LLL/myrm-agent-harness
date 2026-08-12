"""Regression tests for wait strategy timeout handling.

Covers two bug classes found in wait/_impl.py:
1. ``page.evaluate()`` was called with a ``timeout`` kwarg that Patchright does
   not support, causing a TypeError on every SPA_STABLE wait.
2. ``except TimeoutError`` clauses only matched builtins.TimeoutError, missing
   ``patchright.async_api.TimeoutError`` (a distinct class), so real Playwright
   timeouts escaped the handlers and corrupted the fallback logic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from myrm_agent_harness.toolkits.browser.wait import (
    WaitStrategy,
    wait_for_page_ready,
)
from myrm_agent_harness.toolkits.browser.wait._impl import (
    _TIMEOUT_ERRORS,
    wait_dom_stable_only,
    wait_networkidle_only,
    wait_spa_stable,
)


def test_timeout_errors_tuple_covers_both_types() -> None:
    """_TIMEOUT_ERRORS must recognize builtins and Patchright timeouts."""
    assert TimeoutError in _TIMEOUT_ERRORS
    assert PlaywrightTimeoutError in _TIMEOUT_ERRORS


async def test_spa_stable_evaluate_receives_no_timeout_kwarg() -> None:
    """page.evaluate must not receive the unsupported timeout kwarg."""
    captured: dict[str, object] = {}

    async def fake_evaluate(expression: str, **kwargs: object) -> object:
        captured["kwargs"] = kwargs
        return {"reason": "spa_stable", "elapsed_ms": 0}

    page = MagicMock()
    page.evaluate = fake_evaluate

    metrics = await wait_spa_stable(page, max_ms=1000, start_time=0.0)

    assert metrics.reason == "both"
    assert "timeout" not in captured["kwargs"]


async def test_spa_stable_playwright_timeout_returns_capped() -> None:
    """A PlaywrightTimeoutError inside evaluate must yield capped metrics."""
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=PlaywrightTimeoutError("Timeout 30000ms exceeded"))

    metrics = await wait_spa_stable(page, max_ms=100, start_time=0.0)

    assert metrics.strategy == WaitStrategy.SPA_STABLE
    assert metrics.reason == "capped"


async def test_spa_stable_builtin_timeout_returns_capped() -> None:
    """A builtins.TimeoutError inside evaluate must also yield capped metrics."""
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=TimeoutError("capped"))

    metrics = await wait_spa_stable(page, max_ms=100, start_time=0.0)

    assert metrics.reason == "capped"


async def test_networkidle_playwright_timeout_returns_capped() -> None:
    """A PlaywrightTimeoutError inside wait_for_load_state must be handled."""
    page = MagicMock()
    page.wait_for_load_state = AsyncMock(side_effect=PlaywrightTimeoutError("idle timeout"))

    metrics = await wait_networkidle_only(page, max_ms=100, start_time=0.0)

    assert metrics.strategy == WaitStrategy.NETWORKIDLE
    assert metrics.reason == "capped"


async def test_dom_stable_evaluate_timeout_returns_capped() -> None:
    """A PlaywrightTimeoutError inside DOM evaluate must yield capped metrics."""
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=PlaywrightTimeoutError("dom timeout"))

    metrics = await wait_dom_stable_only(page, max_ms=100, quiet_ms=50, start_time=0.0)

    assert metrics.strategy == WaitStrategy.DOM_STABLE
    assert metrics.reason == "capped"


async def test_smart_falls_back_on_playwright_timeout() -> None:
    """SMART fast path timeout must fall back to hybrid instead of crashing."""
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))
    page.wait_for_load_state = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))

    metrics = await wait_for_page_ready(page, strategy=WaitStrategy.SMART, max_ms=100)

    assert metrics.strategy == WaitStrategy.SMART
    assert metrics.reason in ("capped", "first_completed", "both")


async def test_hybrid_playwright_timeout_returns_capped() -> None:
    """HYBRID must degrade gracefully when both detection tasks time out."""
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))
    page.wait_for_load_state = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))

    metrics = await wait_for_page_ready(page, strategy=WaitStrategy.HYBRID, max_ms=100)

    assert metrics.strategy == WaitStrategy.HYBRID
    assert metrics.reason in ("capped", "first_completed", "both")

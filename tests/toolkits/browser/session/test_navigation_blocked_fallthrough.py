"""Tests for blocked HTTP navigation fallthrough to CAPTCHA/stealth ladder."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.captcha.protocols import CaptchaHandleResult, CaptchaType
from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine
from myrm_agent_harness.toolkits.browser.pool import ContextType
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.session.browser_session_navigation_mixin import (
    _camoufox_launch_tool_error,
)
from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError
from myrm_agent_harness.utils.errors import ToolError

from ..test_browser_session import _FakePool


@pytest.fixture()
def store_dir(tmp_path: object) -> str:
    import os
    import myrm_agent_harness.toolkits.browser.pool.engine_affinity as mod

    old_global = mod._global_store
    mod._global_store = None

    data_dir = str(tmp_path)
    with patch.dict(os.environ, {"MYRM_DATA_DIR": data_dir}):
        yield data_dir

    mod._global_store = old_global


@pytest.mark.asyncio
async def test_blocked_403_reaches_captcha_after_proxy_retries() -> None:
    """After proxy retries exhaust on HTTP 403, navigation must reach CAPTCHA detection."""
    session = BrowserSession(_FakePool(), ContextType.AGENT, allow_private_networks=True)
    await session.new_tab()

    goto_calls = 0

    async def blocked_goto(url: str) -> tuple[str, str, int]:
        nonlocal goto_calls
        goto_calls += 1
        return ("Blocked Page", url, 403)

    captcha_invoked = False

    async def fake_handle_captcha() -> CaptchaHandleResult | None:
        nonlocal captcha_invoked
        captcha_invoked = True
        return None

    session._captcha_coordinator = object()  # type: ignore[assignment]
    await session._ensure_components()
    assert session._navigator is not None

    with patch.object(session._navigator, "goto", side_effect=blocked_goto):
        with patch.object(session, "_handle_captcha_if_detected", side_effect=fake_handle_captcha):
            with patch.object(session, "restart", new_callable=AsyncMock):
                result = await session.navigate("https://blocked.example.com")

    assert goto_calls == 3
    assert captcha_invoked is True
    assert "blocked.example.com" in result
    assert "403" in result


@pytest.mark.asyncio
async def test_blocked_429_reaches_captcha_after_proxy_retries() -> None:
    """HTTP 429 uses the same fallthrough path as 403."""
    session = BrowserSession(_FakePool(), ContextType.AGENT, allow_private_networks=True)
    await session.new_tab()

    async def blocked_goto(url: str) -> tuple[str, str, int]:
        return ("Rate Limited", url, 429)

    captcha_invoked = False

    async def fake_handle_captcha() -> CaptchaHandleResult | None:
        nonlocal captcha_invoked
        captcha_invoked = True
        return None

    session._captcha_coordinator = object()  # type: ignore[assignment]
    await session._ensure_components()

    with patch.object(session._navigator, "goto", side_effect=blocked_goto):
        with patch.object(session, "_handle_captcha_if_detected", side_effect=fake_handle_captcha):
            with patch.object(session, "restart", new_callable=AsyncMock):
                result = await session.navigate("https://rate-limited.example.com")

    assert captcha_invoked is True
    assert "429" in result


@pytest.mark.asyncio
async def test_captcha_failure_upgrades_to_camoufox() -> None:
    """Failed CAPTCHA on Patchright must restart with FIREFOX_CAMOUFOX."""
    session = BrowserSession(_FakePool(), ContextType.AGENT, allow_private_networks=True)
    await session.new_tab()

    failed = CaptchaHandleResult(
        success=False,
        challenge_type=CaptchaType.CLOUDFLARE_CHALLENGE.value,
        message="Cloudflare challenge unresolved",
    )

    async def ok_goto(url: str) -> tuple[str, str, int]:
        return ("Challenge", url, 200)

    async def fake_handle_captcha() -> CaptchaHandleResult:
        return failed

    session._captcha_coordinator = object()  # type: ignore[assignment]
    await session._ensure_components()

    restart_mock = AsyncMock()
    notify_mock = AsyncMock()

    with patch.object(session._navigator, "goto", side_effect=ok_goto):
        with patch.object(session, "_handle_captcha_if_detected", side_effect=fake_handle_captcha):
            with patch.object(session, "restart", restart_mock):
                with patch.object(session, "notify_progress", notify_mock):
                    with pytest.raises(ToolError, match="TERMINAL_CHALLENGE"):
                        await session.navigate("https://cf.example.com")

    restart_mock.assert_awaited()
    engine_kw = restart_mock.await_args.kwargs.get("engine")
    assert engine_kw == BrowserEngine.FIREFOX_CAMOUFOX.value
    notify_mock.assert_awaited()
    assert "stealth" in notify_mock.await_args.args[0].lower()


def test_camoufox_install_hint_uses_valid_dependency() -> None:
    """User-facing install hint must not reference invalid camoufox[async] extra."""
    with pytest.raises(ToolError) as exc_info:
        _camoufox_launch_tool_error(BrowserLaunchError("missing binary"))

    hint = exc_info.value.user_hint or ""
    assert "camoufox>=0.4.11" in hint
    assert "camoufox[async]" not in hint


@pytest.mark.asyncio
async def test_captcha_failure_camoufox_retry_success_records_affinity(store_dir: str) -> None:
    """Camoufox upgrade after CAPTCHA failure records engine affinity on success."""
    from myrm_agent_harness.toolkits.browser.pool.engine_affinity import get_engine_affinity_store

    session = BrowserSession(_FakePool(), ContextType.AGENT, allow_private_networks=True)
    await session.new_tab()

    calls = 0
    failed = CaptchaHandleResult(
        success=False,
        challenge_type=CaptchaType.CLOUDFLARE_CHALLENGE.value,
        message="blocked",
    )

    async def fake_handle_captcha() -> CaptchaHandleResult | None:
        nonlocal calls
        calls += 1
        return failed if calls == 1 else None

    async def ok_goto(url: str) -> tuple[str, str, int]:
        return ("OK", url, 200)

    session._captcha_coordinator = object()  # type: ignore[assignment]
    await session._ensure_components()

    with patch.dict(os.environ, {"MYRM_DATA_DIR": store_dir}):
        with patch.object(session._navigator, "goto", side_effect=ok_goto):
            with patch.object(session, "_handle_captcha_if_detected", side_effect=fake_handle_captcha):
                with patch.object(session, "restart", new_callable=AsyncMock):
                    result = await session.navigate("https://cf-success.example.com")

    store = get_engine_affinity_store()
    assert store.get("cf-success.example.com") is BrowserEngine.FIREFOX_CAMOUFOX
    assert "cf-success.example.com" in result

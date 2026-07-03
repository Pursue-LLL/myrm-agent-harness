"""Tests for blocked HTTP navigation fallthrough to CAPTCHA/stealth ladder."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.captcha.protocols import CaptchaHandleResult
from myrm_agent_harness.toolkits.browser.pool import ContextType
from myrm_agent_harness.toolkits.browser.session import BrowserSession

from ..test_browser_session import _FakePool


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

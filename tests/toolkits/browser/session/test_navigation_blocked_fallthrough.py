"""Tests for blocked HTTP navigation fallthrough to CAPTCHA/stealth ladder."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.captcha.protocols import CaptchaHandleResult, CaptchaType
from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError
from myrm_agent_harness.toolkits.browser.pool import ContextType
from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.session.browser_session_navigation_mixin import (
    _camoufox_launch_tool_error,
)
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

    with (
        patch.object(session._navigator, "goto", side_effect=blocked_goto),
        patch.object(session, "_handle_captcha_if_detected", side_effect=fake_handle_captcha),
        patch.object(session, "restart", new_callable=AsyncMock),
    ):
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

    with (
        patch.object(session._navigator, "goto", side_effect=blocked_goto),
        patch.object(session, "_handle_captcha_if_detected", side_effect=fake_handle_captcha),
        patch.object(session, "restart", new_callable=AsyncMock),
    ):
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

    with (
        patch.object(session._navigator, "goto", side_effect=ok_goto),
        patch.object(session, "_handle_captcha_if_detected", side_effect=fake_handle_captcha),
        patch.object(session, "restart", restart_mock),
        patch.object(session, "notify_progress", notify_mock),
        pytest.raises(ToolError, match="TERMINAL_CHALLENGE"),
    ):
        await session.navigate("https://cf.example.com")

    restart_mock.assert_awaited()
    engine_kw = restart_mock.await_args.kwargs.get("engine")
    assert engine_kw == BrowserEngine.FIREFOX_CAMOUFOX.value
    notify_mock.assert_awaited()
    assert "stealth" in notify_mock.await_args.args[0].lower()


def test_camoufox_unavailable_hint_directs_agent_to_human_takeover() -> None:
    """The agent cannot install a browser build; it must be steered to takeover or alternatives."""
    with pytest.raises(ToolError) as exc_info:
        _camoufox_launch_tool_error(BrowserLaunchError("missing binary"))

    err = exc_info.value
    guidance = " ".join([err.user_hint or "", *err.recovery_suggestions])
    assert "browser_ask_human_tool" in (err.user_hint or "")
    assert "browser_ask_human_tool" in err.recovery_suggestions[0]
    for operator_detail in ("pip install", "camoufox fetch", "camoufox>=", "CAMOUFOX_EXECUTABLE_PATH"):
        assert operator_detail not in guidance


@pytest.mark.asyncio
async def test_repeat_navigation_to_terminal_challenge_domain_fails_fast() -> None:
    """The second visit hits the per-domain cache instead of crashing on the TTL lookup."""
    session = BrowserSession(_FakePool(), ContextType.AGENT, allow_private_networks=True)
    await session.new_tab()
    session._engine_preference = BrowserEngine.FIREFOX_CAMOUFOX

    goto_calls = 0

    async def ok_goto(url: str) -> tuple[str, str, int]:
        nonlocal goto_calls
        goto_calls += 1
        return ("Challenge", url, 200)

    failed = CaptchaHandleResult(
        success=False,
        challenge_type=CaptchaType.DATADOME.value,
        message="unsolvable",
    )

    session._captcha_coordinator = object()  # type: ignore[assignment]
    await session._ensure_components()

    with (
        patch.object(session._navigator, "goto", side_effect=ok_goto),
        patch.object(session, "_handle_captcha_if_detected", new=AsyncMock(return_value=failed)),
    ):
        with pytest.raises(ToolError) as first:
            await session.navigate("https://dd.example.com/a")
        assert first.value.error_code == "BROWSER_TERMINAL_CHALLENGE"

        with pytest.raises(ToolError) as second:
            await session.navigate("https://dd.example.com/b")
        assert second.value.error_code == "BROWSER_TERMINAL_CHALLENGE_CACHED"

    assert goto_calls == 1


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

    with (
        patch.dict(os.environ, {"MYRM_DATA_DIR": store_dir}),
        patch.object(session._navigator, "goto", side_effect=ok_goto),
        patch.object(session, "_handle_captcha_if_detected", side_effect=fake_handle_captcha),
        patch.object(session, "restart", new_callable=AsyncMock),
    ):
        result = await session.navigate("https://cf-success.example.com")

    store = get_engine_affinity_store()
    assert store.get("cf-success.example.com") is BrowserEngine.FIREFOX_CAMOUFOX
    assert "cf-success.example.com" in result


@pytest.mark.asyncio
async def test_affinity_hit_is_skipped_when_this_session_cannot_switch_engines(store_dir: str) -> None:
    """A remembered Camoufox hint (global) must not abort navigation in a session that cannot honor it."""
    from myrm_agent_harness.toolkits.browser.exceptions import EngineUnavailableError
    from myrm_agent_harness.toolkits.browser.pool.engine_affinity import get_engine_affinity_store

    store = get_engine_affinity_store()
    store.record("hinted.example.com", BrowserEngine.FIREFOX_CAMOUFOX)
    session = BrowserSession(_FakePool(), ContextType.AGENT, allow_private_networks=True)
    await session.new_tab()
    await session._ensure_components()
    restart = AsyncMock(side_effect=EngineUnavailableError("not applicable"))

    async def ok_goto(url: str) -> tuple[str, str, int]:
        return ("OK", url, 200)

    with (
        patch.dict(os.environ, {"MYRM_DATA_DIR": store_dir}),
        patch.object(session._navigator, "goto", side_effect=ok_goto),
        patch.object(session, "restart", restart),
    ):
        result = await session.navigate("https://hinted.example.com")

    restart.assert_awaited_once()
    assert "hinted.example.com" in result
    assert store.get("hinted.example.com") is BrowserEngine.FIREFOX_CAMOUFOX
    assert session._engine_preference is None


@pytest.mark.asyncio
async def test_affinity_hit_launch_failure_clears_hint_and_reports_unavailable(store_dir: str) -> None:
    from myrm_agent_harness.toolkits.browser.pool.engine_affinity import get_engine_affinity_store

    store = get_engine_affinity_store()
    store.record("stale.example.com", BrowserEngine.FIREFOX_CAMOUFOX)
    session = BrowserSession(_FakePool(), ContextType.AGENT, allow_private_networks=True)
    await session.new_tab()
    await session._ensure_components()

    with (
        patch.dict(os.environ, {"MYRM_DATA_DIR": store_dir}),
        patch.object(session, "restart", AsyncMock(side_effect=BrowserLaunchError("launch failed"))),
        pytest.raises(ToolError) as exc_info,
    ):
        await session.navigate("https://stale.example.com")

    assert exc_info.value.error_code == "BROWSER_CAMOUFOX_UNAVAILABLE"
    assert store.get("stale.example.com") is None


@pytest.mark.asyncio
async def test_camoufox_retry_served_a_block_page_does_not_record_affinity(store_dir: str) -> None:
    """A 403/429 on the upgraded retry is not a success; remembering it would pin the domain to a failing engine."""
    from myrm_agent_harness.toolkits.browser.pool.engine_affinity import get_engine_affinity_store

    session = BrowserSession(_FakePool(), ContextType.AGENT, allow_private_networks=True)
    await session.new_tab()

    captcha_calls = 0
    goto_calls = 0
    failed = CaptchaHandleResult(
        success=False,
        challenge_type=CaptchaType.CLOUDFLARE_CHALLENGE.value,
        message="blocked",
    )

    async def fake_handle_captcha() -> CaptchaHandleResult | None:
        nonlocal captcha_calls
        captcha_calls += 1
        return failed if captcha_calls == 1 else None

    async def goto_then_blocked(url: str) -> tuple[str, str, int]:
        nonlocal goto_calls
        goto_calls += 1
        return ("Blocked", url, 200 if goto_calls == 1 else 403)

    session._captcha_coordinator = object()  # type: ignore[assignment]
    await session._ensure_components()

    with (
        patch.dict(os.environ, {"MYRM_DATA_DIR": store_dir}),
        patch.object(session._navigator, "goto", side_effect=goto_then_blocked),
        patch.object(session, "_handle_captcha_if_detected", side_effect=fake_handle_captcha),
        patch.object(session, "restart", new_callable=AsyncMock),
    ):
        await session.navigate("https://cf-blocked-retry.example.com")

    assert goto_calls == 2
    assert get_engine_affinity_store().get("cf-blocked-retry.example.com") is None

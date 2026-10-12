"""BrowserSession.restart engine switching: pre-flight refusal and failure rollback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError, EngineUnavailableError
from myrm_agent_harness.toolkits.browser.pool import ContextType
from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine
from myrm_agent_harness.toolkits.browser.session import BrowserSession

from ..test_browser_session import _FakePage, _FakePool

_REASON_PROBE = "myrm_agent_harness.toolkits.browser.pool.camoufox_availability.camoufox_unavailable_reason"
_CAMOUFOX = BrowserEngine.FIREFOX_CAMOUFOX.value
_COOKIE = {"name": "sid", "value": "1", "domain": "example.com", "path": "/"}


class _EnginePool(_FakePool):
    """Fake pool whose page acquisition fails for selected engines and records every request."""

    def __init__(self, *, managed: bool = True) -> None:
        super().__init__()
        self.managed = managed
        self.failing_engines: set[str | None] = set()
        self.requested_engines: list[str | None] = []

    def is_managed_for_page(self, page: object) -> bool:
        return self.managed

    async def acquire_page(
        self,
        context_type: object,
        context_key: str | None = None,
        context_kwargs: dict[str, object] | None = None,
        engine_preference: str | None = None,
        launch_mode_preference: str | None = None,
    ) -> tuple[_FakePage, str]:
        engine = str(engine_preference) if engine_preference is not None else None
        self.requested_engines.append(engine)
        if engine in self.failing_engines:
            raise BrowserLaunchError(f"cannot launch {engine}")
        return await super().acquire_page(context_type, context_key, context_kwargs, engine_preference)


async def _open_session(pool: _EnginePool) -> BrowserSession:
    session = BrowserSession(pool, ContextType.AGENT, allow_private_networks=True)
    await session.new_tab()
    session._tab_controller.get_active_page().url = "https://example.com/account"
    session._tab_controller.get_active_page().context.storage_state = AsyncMock(
        return_value={"cookies": [_COOKIE], "origins": []}
    )
    pool.requested_engines.clear()
    return session


@pytest.mark.asyncio
async def test_switch_refused_when_engine_not_ready_leaves_session_untouched() -> None:
    pool = _EnginePool()
    session = await _open_session(pool)
    page_before = session._tab_controller.get_active_page()
    tabs_before = session.list_tabs()

    with (
        patch(_REASON_PROBE, return_value="Camoufox browser build is not installed"),
        patch.object(session, "close", new_callable=AsyncMock) as close,
        pytest.raises(EngineUnavailableError, match="not installed"),
    ):
        await session.restart(engine=_CAMOUFOX, restore_url=False)

    close.assert_not_awaited()
    assert pool.requested_engines == []
    assert session.list_tabs() == tabs_before
    assert session._tab_controller.get_active_page() is page_before
    assert session._engine_preference is None


@pytest.mark.asyncio
async def test_switch_refused_for_attached_real_browser() -> None:
    """An engine swap would tear down a user's own browser contexts; it must not even start."""
    pool = _EnginePool(managed=False)
    session = await _open_session(pool)
    page_before = session._tab_controller.get_active_page()

    with (
        patch(_REASON_PROBE, return_value=None),
        patch.object(session, "close", new_callable=AsyncMock) as close,
        pytest.raises(EngineUnavailableError, match="attached real browser"),
    ):
        await session.restart(engine=_CAMOUFOX, restore_url=False)

    close.assert_not_awaited()
    assert pool.requested_engines == []
    assert session._tab_controller.get_active_page() is page_before
    assert session._engine_preference is None


@pytest.mark.asyncio
async def test_failed_switch_rolls_back_and_session_stays_usable() -> None:
    pool = _EnginePool()
    session = await _open_session(pool)
    pool.failing_engines = {_CAMOUFOX}

    with (
        patch(_REASON_PROBE, return_value=None),
        pytest.raises(BrowserLaunchError, match="cannot launch firefox_camoufox"),
    ):
        await session.restart(engine=_CAMOUFOX, restore_url=False)

    assert pool.requested_engines == [_CAMOUFOX, None]
    assert session._engine_preference is None
    assert len(session.list_tabs()) == 1
    restored_page = session._tab_controller.get_active_page()
    restored_page.context.add_cookies.assert_awaited_once_with([_COOKIE])

    pool.requested_engines.clear()
    assert "example.com" in await session.navigate("https://example.com")
    assert pool.requested_engines == []
    await session.new_tab()
    assert pool.requested_engines == [None]


@pytest.mark.asyncio
async def test_failed_switch_restores_a_non_default_previous_engine() -> None:
    pool = _EnginePool()
    session = await _open_session(pool)
    session._engine_preference = BrowserEngine.CHROMIUM_PATCHRIGHT
    pool.failing_engines = {_CAMOUFOX}

    with patch(_REASON_PROBE, return_value=None), pytest.raises(BrowserLaunchError):
        await session.restart(engine=_CAMOUFOX, restore_url=False)

    assert session._engine_preference is BrowserEngine.CHROMIUM_PATCHRIGHT
    assert pool.requested_engines == [_CAMOUFOX, BrowserEngine.CHROMIUM_PATCHRIGHT.value]


@pytest.mark.asyncio
async def test_successful_switch_keeps_new_engine() -> None:
    pool = _EnginePool()
    session = await _open_session(pool)

    with patch(_REASON_PROBE, return_value=None):
        message = await session.restart(engine=_CAMOUFOX, restore_url=False)

    assert "Successfully restarted" in message
    assert session._engine_preference is BrowserEngine.FIREFOX_CAMOUFOX
    assert pool.requested_engines == [_CAMOUFOX]


@pytest.mark.asyncio
async def test_same_engine_restart_failure_is_raised_without_a_second_attempt() -> None:
    """Proxy-rotation restarts (no engine switch) have nothing to roll back to."""
    pool = _EnginePool()
    session = await _open_session(pool)
    pool.failing_engines = {None}

    with pytest.raises(BrowserLaunchError, match="cannot launch None"):
        await session.restart(restore_url=False)

    assert pool.requested_engines == [None]


@pytest.mark.asyncio
async def test_invalid_engine_name_keeps_current_preference() -> None:
    pool = _EnginePool()
    session = await _open_session(pool)

    message = await session.restart(engine="not-an-engine", restore_url=False)

    assert "Successfully restarted" in message
    assert session._engine_preference is None
    assert pool.requested_engines == [None]

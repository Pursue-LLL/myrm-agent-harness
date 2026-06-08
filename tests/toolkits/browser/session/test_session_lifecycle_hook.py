"""Unit tests for session lifecycle hook infrastructure.

Covers:
- SessionLifecycleHookProtocol runtime-checkable conformance
- _fire_and_forget background task scheduling and error logging
- _parse_counts regex extraction from save result strings
- Mixin hook wiring (set_session_lifecycle_hook)
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
    _fire_and_forget,
    _parse_counts,
)
from myrm_agent_harness.toolkits.browser.session.session_lifecycle_hook import (
    SessionLifecycleHookProtocol,
)


# ===========================================================================
# Protocol conformance
# ===========================================================================


class TestSessionLifecycleHookProtocol:
    def test_runtime_checkable(self) -> None:
        """Protocol is runtime_checkable — isinstance works."""

        class Good:
            async def on_session_saved(self, domain: str, cookie_count: int, local_storage_count: int) -> None: ...
            async def on_session_deleted(self, domain: str) -> None: ...
            async def on_sessions_expired(self, domains: list[str]) -> None: ...

        assert isinstance(Good(), SessionLifecycleHookProtocol)

    def test_incomplete_impl_rejected(self) -> None:
        class Bad:
            async def on_session_saved(self, domain: str, cookie_count: int, local_storage_count: int) -> None: ...

        assert not isinstance(Bad(), SessionLifecycleHookProtocol)


# ===========================================================================
# _parse_counts
# ===========================================================================


class TestParseCounts:
    def test_standard_format(self) -> None:
        result = "Saved encrypted session for example.com (15 cookies, 7 localStorage items)"
        assert _parse_counts(result) == (15, 7)

    def test_zero_cookies(self) -> None:
        result = "Saved encrypted session for test.com (0 cookies, 3 localStorage items)"
        assert _parse_counts(result) == (0, 3)

    def test_zero_local_storage(self) -> None:
        result = "Saved encrypted session for test.com (5 cookies, 0 localStorage items)"
        assert _parse_counts(result) == (5, 0)

    def test_no_match_returns_zeros(self) -> None:
        assert _parse_counts("Some unrecognized format") == (0, 0)

    def test_empty_string(self) -> None:
        assert _parse_counts("") == (0, 0)

    def test_only_cookies_match(self) -> None:
        assert _parse_counts("42 cookies total") == (42, 0)

    def test_only_local_storage_match(self) -> None:
        assert _parse_counts("has 99 localStorage entries") == (0, 99)


# ===========================================================================
# _fire_and_forget
# ===========================================================================


class TestFireAndForget:
    @pytest.mark.asyncio
    async def test_successful_coroutine(self) -> None:
        called = asyncio.Event()

        async def task() -> None:
            called.set()

        _fire_and_forget(task())
        await asyncio.sleep(0.05)
        assert called.is_set()

    @pytest.mark.asyncio
    async def test_exception_logged_not_raised(self, caplog: pytest.LogCaptureFixture) -> None:
        async def bad_task() -> None:
            raise ValueError("boom")

        with caplog.at_level(logging.WARNING):
            _fire_and_forget(bad_task())
            await asyncio.sleep(0.05)

        assert any("fire-and-forget failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_cancelled_task_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        async def slow_task() -> None:
            await asyncio.sleep(10)

        with caplog.at_level(logging.WARNING):
            _fire_and_forget(slow_task())
            await asyncio.sleep(0)
            for task in asyncio.all_tasks():
                if task.get_coro().__qualname__ == "TestFireAndForget.test_cancelled_task_no_warning.<locals>.slow_task":
                    task.cancel()
                    break
            await asyncio.sleep(0.05)

        assert not any("fire-and-forget failed" in r.message for r in caplog.records)


# ===========================================================================
# Mixin hook wiring
# ===========================================================================


class TestMixinHookWiring:
    def test_set_session_lifecycle_hook(self) -> None:
        from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
            BrowserSessionPersistenceMixin,
        )

        mixin = BrowserSessionPersistenceMixin()
        hook = MagicMock(spec=SessionLifecycleHookProtocol)
        mixin.set_session_lifecycle_hook(hook)
        assert mixin._session_lifecycle_hook is hook

    @pytest.mark.asyncio
    async def test_save_triggers_hook(self) -> None:
        """Save session fires on_session_saved via the hook."""
        from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
            BrowserSessionPersistenceMixin,
        )

        mixin = BrowserSessionPersistenceMixin()
        mixin._persistence = MagicMock()
        mixin._persistence.save = AsyncMock(
            return_value="Saved encrypted session for x.com (5 cookies, 2 localStorage items)"
        )
        mixin._persistence.compute_hash = AsyncMock(return_value="abc123")
        mixin._session_hash_cache = {}

        mock_page = MagicMock()
        mock_tab_ctrl = MagicMock()
        mock_tab_ctrl.get_active_page.return_value = mock_page
        mixin._tab_controller = mock_tab_ctrl
        mixin._ensure_components = AsyncMock()

        hook = AsyncMock(spec=SessionLifecycleHookProtocol)
        mixin.set_session_lifecycle_hook(hook)

        await mixin.save_session("x.com")
        await asyncio.sleep(0.05)

        hook.on_session_saved.assert_awaited_once_with("x.com", 5, 2)

    @pytest.mark.asyncio
    async def test_delete_triggers_hook(self) -> None:
        """Delete session fires on_session_deleted via the hook."""
        from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
            BrowserSessionPersistenceMixin,
        )

        mixin = BrowserSessionPersistenceMixin()
        mixin._persistence = MagicMock()
        mixin._persistence.delete = AsyncMock(return_value="Deleted session for y.com")

        hook = AsyncMock(spec=SessionLifecycleHookProtocol)
        mixin.set_session_lifecycle_hook(hook)

        await mixin.delete_session("y.com")
        await asyncio.sleep(0.05)

        hook.on_session_deleted.assert_awaited_once_with("y.com")

    @pytest.mark.asyncio
    async def test_save_error_does_not_trigger_hook(self) -> None:
        """When save returns an error string, hook is NOT fired."""
        from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
            BrowserSessionPersistenceMixin,
        )

        mixin = BrowserSessionPersistenceMixin()
        mixin._persistence = MagicMock()
        mixin._persistence.save = AsyncMock(return_value="Error: encryption failed")
        mixin._ensure_components = AsyncMock()

        mock_page = MagicMock()
        mock_tab_ctrl = MagicMock()
        mock_tab_ctrl.get_active_page.return_value = mock_page
        mixin._tab_controller = mock_tab_ctrl

        hook = AsyncMock(spec=SessionLifecycleHookProtocol)
        mixin.set_session_lifecycle_hook(hook)

        await mixin.save_session("err.com")
        await asyncio.sleep(0.05)

        hook.on_session_saved.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_no_saved_does_not_trigger_hook(self) -> None:
        """When delete returns 'No saved session', hook is NOT fired."""
        from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
            BrowserSessionPersistenceMixin,
        )

        mixin = BrowserSessionPersistenceMixin()
        mixin._persistence = MagicMock()
        mixin._persistence.delete = AsyncMock(return_value="No saved session for z.com")

        hook = AsyncMock(spec=SessionLifecycleHookProtocol)
        mixin.set_session_lifecycle_hook(hook)

        await mixin.delete_session("z.com")
        await asyncio.sleep(0.05)

        hook.on_session_deleted.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_save_invalid_domain_no_hook(self) -> None:
        """Invalid domain name returns error, hook is NOT fired."""
        from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
            BrowserSessionPersistenceMixin,
        )

        mixin = BrowserSessionPersistenceMixin()
        mixin._persistence = MagicMock()
        mixin._ensure_components = AsyncMock()

        hook = AsyncMock(spec=SessionLifecycleHookProtocol)
        mixin.set_session_lifecycle_hook(hook)

        result = await mixin.save_session("../../../etc/passwd")
        assert "Error" in result
        hook.on_session_saved.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_invalid_domain_no_hook(self) -> None:
        """Invalid domain name returns error, hook is NOT fired."""
        from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
            BrowserSessionPersistenceMixin,
        )

        mixin = BrowserSessionPersistenceMixin()
        mixin._persistence = MagicMock()

        hook = AsyncMock(spec=SessionLifecycleHookProtocol)
        mixin.set_session_lifecycle_hook(hook)

        result = await mixin.delete_session("../../etc/passwd")
        assert "Error" in result
        hook.on_session_deleted.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_save_hash_none_still_fires_hook(self) -> None:
        """When compute_hash returns None, hook still fires."""
        from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
            BrowserSessionPersistenceMixin,
        )

        mixin = BrowserSessionPersistenceMixin()
        mixin._persistence = MagicMock()
        mixin._persistence.save = AsyncMock(
            return_value="Saved encrypted session for x.com (3 cookies, 1 localStorage items)"
        )
        mixin._persistence.compute_hash = AsyncMock(return_value=None)
        mixin._session_hash_cache = {}
        mixin._ensure_components = AsyncMock()

        mock_page = MagicMock()
        mock_tab_ctrl = MagicMock()
        mock_tab_ctrl.get_active_page.return_value = mock_page
        mixin._tab_controller = mock_tab_ctrl

        hook = AsyncMock(spec=SessionLifecycleHookProtocol)
        mixin.set_session_lifecycle_hook(hook)

        await mixin.save_session("x.com")
        await asyncio.sleep(0.05)

        hook.on_session_saved.assert_awaited_once_with("x.com", 3, 1)
        assert "x.com" not in mixin._session_hash_cache

    @pytest.mark.asyncio
    async def test_no_hook_no_error(self) -> None:
        """Operations work fine when no hook is set."""
        from myrm_agent_harness.toolkits.browser.session.browser_session_persistence_mixin import (
            BrowserSessionPersistenceMixin,
        )

        mixin = BrowserSessionPersistenceMixin()
        mixin._persistence = MagicMock()
        mixin._persistence.save = AsyncMock(
            return_value="Saved encrypted session for no-hook.com (1 cookies, 0 localStorage items)"
        )
        mixin._persistence.compute_hash = AsyncMock(return_value="hash")
        mixin._session_hash_cache = {}
        mixin._ensure_components = AsyncMock()

        mock_page = MagicMock()
        mock_tab_ctrl = MagicMock()
        mock_tab_ctrl.get_active_page.return_value = mock_page
        mixin._tab_controller = mock_tab_ctrl

        result = await mixin.save_session("no-hook.com")
        assert "Saved" in result

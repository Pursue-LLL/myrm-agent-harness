"""Unit tests for BrowserLauncher CDP connect, three-mode routing, external browser awareness."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError
from myrm_agent_harness.toolkits.browser.pool import GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.browser_launcher import (
    BrowserInstance,
    BrowserLauncher,
)
from myrm_agent_harness.toolkits.browser.pool.config import (
    _DEFAULT_CDP_ENDPOINT,
    BrowserConfig,
    LaunchMode,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_browser(contexts: int = 0) -> MagicMock:
    browser = MagicMock()
    browser.contexts = [MagicMock() for _ in range(contexts)]
    return browser


def _make_launcher(
    launch_mode: LaunchMode = LaunchMode.LAUNCH,
    cdp_endpoint: str | None = None,
) -> BrowserLauncher:
    return BrowserLauncher(
        launch_options={"headless": True},
        launch_mode=launch_mode,
        cdp_endpoint=cdp_endpoint,
    )


# ---------------------------------------------------------------------------
# BrowserInstance.is_managed
# ---------------------------------------------------------------------------


class TestBrowserInstanceIsManaged:
    def test_default_is_managed_true(self) -> None:
        inst = BrowserInstance(browser=_mock_browser())
        assert inst.is_managed is True

    def test_explicit_is_managed_false(self) -> None:
        inst = BrowserInstance(browser=_mock_browser(), is_managed=False)
        assert inst.is_managed is False


# ---------------------------------------------------------------------------
# BrowserLauncher init
# ---------------------------------------------------------------------------


class TestBrowserLauncherInit:
    def test_default_launch_mode(self) -> None:
        launcher = _make_launcher()
        assert launcher._launch_mode == LaunchMode.LAUNCH

    def test_custom_launch_mode(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.CONNECT, cdp_endpoint="http://host:1234")
        assert launcher._launch_mode == LaunchMode.CONNECT
        assert launcher._cdp_endpoint == "http://host:1234"

    def test_cdp_endpoint_defaults_when_none(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.AUTO, cdp_endpoint=None)
        assert launcher._cdp_endpoint == _DEFAULT_CDP_ENDPOINT


# ---------------------------------------------------------------------------
# _probe_cdp
# ---------------------------------------------------------------------------


class TestProbeCdp:
    @pytest.mark.asyncio
    async def test_probe_success(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.AUTO)
        with patch(
            "myrm_agent_harness.toolkits.browser.pool.chrome_discovery.probe_cdp_endpoint",
            return_value=True,
        ):
            result = await launcher._probe_cdp("http://127.0.0.1:9222")
            assert result is True

    @pytest.mark.asyncio
    async def test_probe_failure_connection_refused(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.AUTO)
        with patch(
            "myrm_agent_harness.toolkits.browser.pool.chrome_discovery.probe_cdp_endpoint",
            return_value=False,
        ):
            result = await launcher._probe_cdp("http://127.0.0.1:9222")
            assert result is False

    @pytest.mark.asyncio
    async def test_probe_failure_timeout(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.AUTO)
        with patch(
            "myrm_agent_harness.toolkits.browser.pool.chrome_discovery.probe_cdp_endpoint",
            return_value=False,
        ):
            result = await launcher._probe_cdp("http://127.0.0.1:9222")
            assert result is False

    @pytest.mark.asyncio
    async def test_probe_ws_endpoint_uses_tcp(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.AUTO)
        with patch(
            "myrm_agent_harness.toolkits.browser.pool.chrome_discovery.probe_cdp_endpoint",
            return_value=True,
        ) as mock_probe:
            result = await launcher._probe_cdp("ws://127.0.0.1:9222/devtools/browser/abc")
            assert result is True
            mock_probe.assert_called_once_with("ws://127.0.0.1:9222/devtools/browser/abc")


# ---------------------------------------------------------------------------
# _connect_existing
# ---------------------------------------------------------------------------


class TestConnectExisting:
    @pytest.mark.asyncio
    async def test_connect_success_returns_unmanaged_instance(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.CONNECT)
        mock_browser = _mock_browser(contexts=2)

        mock_pw = MagicMock()
        mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        launcher._playwright = mock_pw

        inst = await launcher._connect_existing("http://127.0.0.1:9222")

        assert isinstance(inst, BrowserInstance)
        assert inst.is_managed is False
        assert inst.browser is mock_browser
        assert launcher._total_browsers == 1

    @pytest.mark.asyncio
    async def test_connect_failure_raises_after_3_retries(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.CONNECT)

        mock_pw = MagicMock()
        mock_pw.chromium.connect_over_cdp = AsyncMock(side_effect=ConnectionError("refused"))
        launcher._playwright = mock_pw

        with pytest.raises(BrowserLaunchError, match="after 3 attempts"):
            await launcher._connect_existing("http://127.0.0.1:9222")

        assert mock_pw.chromium.connect_over_cdp.await_count == 3

    @pytest.mark.asyncio
    async def test_connect_retry_succeeds_on_second_attempt(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.CONNECT)
        mock_browser = _mock_browser(contexts=1)

        mock_pw = MagicMock()
        mock_pw.chromium.connect_over_cdp = AsyncMock(
            side_effect=[ConnectionError("refused"), mock_browser]
        )
        launcher._playwright = mock_pw

        inst = await launcher._connect_existing("http://127.0.0.1:9222")

        assert inst.is_managed is False
        assert inst.browser is mock_browser
        assert mock_pw.chromium.connect_over_cdp.await_count == 2


# ---------------------------------------------------------------------------
# create_browser routing
# ---------------------------------------------------------------------------


class TestCreateBrowserRouting:
    @pytest.mark.asyncio
    async def test_launch_mode_calls_launch_new(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.LAUNCH)
        expected = BrowserInstance(browser=_mock_browser(), is_managed=True)

        with patch.object(launcher, "_launch_new_browser", AsyncMock(return_value=expected)) as mock_launch:
            result = await launcher.create_browser()

            mock_launch.assert_awaited_once()
            assert result.is_managed is True

    @pytest.mark.asyncio
    async def test_connect_mode_calls_connect_existing(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.CONNECT)
        expected = BrowserInstance(browser=_mock_browser(), is_managed=False)

        with patch.object(launcher, "_connect_existing", AsyncMock(return_value=expected)) as mock_connect:
            result = await launcher.create_browser()

            mock_connect.assert_awaited_once_with(launcher._cdp_endpoint, headers=None)
            assert result.is_managed is False

    @pytest.mark.asyncio
    async def test_auto_mode_probe_success_connects(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.AUTO)
        expected = BrowserInstance(browser=_mock_browser(), is_managed=False)

        with (
            patch.object(launcher, "_probe_cdp", AsyncMock(return_value=True)),
            patch.object(launcher, "_connect_existing", AsyncMock(return_value=expected)) as mock_connect,
            patch.object(launcher, "_launch_new_browser", AsyncMock()) as mock_launch,
        ):
            result = await launcher.create_browser()

            mock_connect.assert_awaited_once()
            mock_launch.assert_not_awaited()
            assert result.is_managed is False

    @pytest.mark.asyncio
    async def test_auto_mode_probe_fail_falls_back_to_launch(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.AUTO)
        expected = BrowserInstance(browser=_mock_browser(), is_managed=True)

        with (
            patch.object(launcher, "_probe_cdp", AsyncMock(return_value=False)),
            patch.object(launcher, "_connect_existing", AsyncMock()) as mock_connect,
            patch.object(launcher, "_launch_new_browser", AsyncMock(return_value=expected)) as mock_launch,
        ):
            result = await launcher.create_browser()

            mock_connect.assert_not_awaited()
            mock_launch.assert_awaited_once()
            assert result.is_managed is True

    @pytest.mark.asyncio
    async def test_auto_mode_probe_ok_but_connect_fails_falls_back(self) -> None:
        launcher = _make_launcher(launch_mode=LaunchMode.AUTO)
        expected = BrowserInstance(browser=_mock_browser(), is_managed=True)

        with (
            patch.object(launcher, "_probe_cdp", AsyncMock(return_value=True)),
            patch.object(launcher, "_connect_existing", AsyncMock(side_effect=Exception("connect err"))),
            patch.object(launcher, "_launch_new_browser", AsyncMock(return_value=expected)) as mock_launch,
        ):
            result = await launcher.create_browser()

            mock_launch.assert_awaited_once()
            assert result.is_managed is True


# ---------------------------------------------------------------------------
# CrashWatchdog: external browser awareness
# ---------------------------------------------------------------------------


class TestCrashWatchdogExternalBrowser:
    @pytest.mark.asyncio
    async def test_external_browser_disconnect_does_not_increment_crash_count(self) -> None:
        pool = GlobalBrowserPool(max_browsers=2)

        mock_browser = _mock_browser()
        mock_browser.on = MagicMock()
        mock_browser.close = AsyncMock()

        inst = BrowserInstance(browser=mock_browser, is_managed=False)
        inst.load = 2

        pool._browsers.append(inst)
        pool._current_pages_in_use = 2

        initial_crash_count = pool._crash_count_browser

        await pool._handle_browser_disconnected(inst)

        assert pool._crash_count_browser == initial_crash_count
        assert inst not in pool._browsers
        assert pool._current_pages_in_use == 0

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_managed_browser_disconnect_increments_crash_count(self) -> None:
        pool = GlobalBrowserPool(max_browsers=2)

        mock_browser = _mock_browser()
        mock_browser.on = MagicMock()
        mock_browser.close = AsyncMock()

        inst = BrowserInstance(browser=mock_browser, is_managed=True)
        inst.load = 1

        pool._browsers.append(inst)
        pool._current_pages_in_use = 1

        initial_crash_count = pool._crash_count_browser

        await pool._handle_browser_disconnected(inst)

        assert pool._crash_count_browser == initial_crash_count + 1
        assert inst not in pool._browsers

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_external_disconnect_does_not_trigger_circuit_breaker(self) -> None:
        config = BrowserConfig.defensive()
        pool = GlobalBrowserPool(max_browsers=2, config=config)

        mock_browser = _mock_browser()
        mock_browser.on = MagicMock()
        mock_browser.close = AsyncMock()

        inst = BrowserInstance(browser=mock_browser, is_managed=False)
        pool._browsers.append(inst)

        cb = pool._circuit_breaker
        assert cb is not None
        crash_domain = cb._GLOBAL_CRASH_DOMAIN
        initial_failures = cb._failure_counts[crash_domain]

        await pool._handle_browser_disconnected(inst)

        assert cb._failure_counts[crash_domain] == initial_failures

        await pool.shutdown()


# ---------------------------------------------------------------------------
# Pool stats: external_browsers and launch_mode fields
# ---------------------------------------------------------------------------


class TestPoolStatsExternalFields:
    @pytest.mark.asyncio
    async def test_stats_includes_launch_mode(self) -> None:
        import dataclasses

        config = dataclasses.replace(BrowserConfig.minimal(), launch_mode=LaunchMode.AUTO)
        pool = GlobalBrowserPool(max_browsers=2, config=config)

        stats = pool.stats
        assert stats["launch_mode"] == "auto"

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_stats_counts_external_browsers(self) -> None:
        pool = GlobalBrowserPool(max_browsers=3)

        managed = BrowserInstance(browser=_mock_browser(), is_managed=True)
        external = BrowserInstance(browser=_mock_browser(), is_managed=False)

        pool._browsers.extend([managed, external])

        stats = pool.stats
        assert stats["total_browsers"] == 2
        assert stats["external_browsers"] == 1

        pool._browsers.clear()
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_stats_browser_detail_includes_is_managed(self) -> None:
        pool = GlobalBrowserPool(max_browsers=2)

        inst = BrowserInstance(browser=_mock_browser(), is_managed=False)
        pool._browsers.append(inst)

        stats = pool.stats
        assert stats["browsers"][0]["is_managed"] is False

        pool._browsers.clear()
        await pool.shutdown()


# ---------------------------------------------------------------------------
# pool.health() includes launch_mode and external_browsers
# ---------------------------------------------------------------------------


class TestPoolHealthExternalFields:
    @pytest.mark.asyncio
    async def test_health_includes_pool_with_launch_mode(self) -> None:
        import dataclasses

        config = dataclasses.replace(BrowserConfig.minimal(), launch_mode=LaunchMode.AUTO)
        pool = GlobalBrowserPool(max_browsers=2, config=config)

        health = await pool.health()

        assert health["status"] == "healthy"
        assert "pool" in health
        pool_stats = health["pool"]
        assert pool_stats["launch_mode"] == "auto"

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_health_includes_external_browsers_count(self) -> None:
        pool = GlobalBrowserPool(max_browsers=3)

        managed = BrowserInstance(browser=_mock_browser(), is_managed=True)
        managed.browser.version = AsyncMock(return_value="v1")
        external = BrowserInstance(browser=_mock_browser(), is_managed=False)
        external.browser.version = AsyncMock(return_value="v2")

        pool._browsers.extend([managed, external])

        health = await pool.health()
        pool_stats = health["pool"]
        assert pool_stats["external_browsers"] == 1
        assert pool_stats["total_browsers"] == 2

        pool._browsers.clear()
        await pool.shutdown()


# ---------------------------------------------------------------------------
# lifecycle_tick: external browser awareness
# ---------------------------------------------------------------------------


class TestLifecycleTickExternalBrowser:
    @pytest.mark.asyncio
    async def test_lifecycle_tick_external_unresponsive_no_crash_count(self) -> None:
        pool = GlobalBrowserPool(max_browsers=2)

        mock_browser = _mock_browser()
        mock_browser.on = MagicMock()
        mock_browser.close = AsyncMock()
        mock_browser.version = AsyncMock(side_effect=TimeoutError("unresponsive"))

        inst = BrowserInstance(browser=mock_browser, is_managed=False)
        inst.load = 1
        pool._browsers.append(inst)
        pool._current_pages_in_use = 1

        initial_crash_count = pool._crash_count_browser

        await pool._lifecycle_tick()

        assert pool._crash_count_browser == initial_crash_count
        assert inst not in pool._browsers

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_lifecycle_tick_managed_unresponsive_increments_crash_count(self) -> None:
        pool = GlobalBrowserPool(max_browsers=2)

        mock_browser = _mock_browser()
        mock_browser.on = MagicMock()
        mock_browser.close = AsyncMock()
        mock_browser.version = AsyncMock(side_effect=TimeoutError("unresponsive"))

        inst = BrowserInstance(browser=mock_browser, is_managed=True)
        inst.load = 1
        pool._browsers.append(inst)
        pool._current_pages_in_use = 1

        initial_crash_count = pool._crash_count_browser

        await pool._lifecycle_tick()

        assert pool._crash_count_browser == initial_crash_count + 1
        assert inst not in pool._browsers

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_lifecycle_tick_external_unresponsive_no_circuit_breaker(self) -> None:
        config = BrowserConfig.defensive()
        pool = GlobalBrowserPool(max_browsers=2, config=config)

        mock_browser = _mock_browser()
        mock_browser.on = MagicMock()
        mock_browser.close = AsyncMock()
        mock_browser.version = AsyncMock(side_effect=TimeoutError("unresponsive"))

        inst = BrowserInstance(browser=mock_browser, is_managed=False)
        pool._browsers.append(inst)

        cb = pool._circuit_breaker
        assert cb is not None
        crash_domain = cb._GLOBAL_CRASH_DOMAIN
        initial_failures = cb._failure_counts[crash_domain]

        await pool._lifecycle_tick()

        assert cb._failure_counts[crash_domain] == initial_failures
        assert inst not in pool._browsers

        await pool.shutdown()


# ---------------------------------------------------------------------------
# CircuitBreaker.record_failure with URL
# ---------------------------------------------------------------------------


class TestCircuitBreakerRecordFailure:
    def test_record_failure_no_url_uses_global_domain(self) -> None:
        from myrm_agent_harness.toolkits.browser.pool.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        assert cb._failure_counts[cb._GLOBAL_CRASH_DOMAIN] == 1

    def test_record_failure_with_url_uses_domain(self) -> None:
        from myrm_agent_harness.toolkits.browser.pool.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure("http://example.com/page")
        assert cb._failure_counts["example.com"] == 1
        assert cb._failure_counts[cb._GLOBAL_CRASH_DOMAIN] == 0

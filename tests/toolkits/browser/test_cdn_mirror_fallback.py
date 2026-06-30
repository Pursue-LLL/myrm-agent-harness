"""Unit tests for CDN mirror fallback in browser_launcher.py.

Covers:
- _get_install_env(): user-set env, CDN reachable, HTTPError, CDN unreachable
- _auto_install_chromium(): integration with _get_install_env
- _build_install_failure_message(): mirror hint presence
"""

from __future__ import annotations

import asyncio
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool.browser_launcher import (
    _build_install_failure_message,
    _CDN_PROBE_URL,
    _CN_MIRROR_CHROMIUM_HOST,
    _CN_MIRROR_HOST,
    _get_install_env,
)


class TestGetInstallEnv:
    """Tests for _get_install_env() — CDN probe and mirror fallback logic."""

    def test_user_set_env_skips_probe(self) -> None:
        with patch.dict("os.environ", {"PLAYWRIGHT_DOWNLOAD_HOST": "https://custom.mirror"}, clear=False):
            env = _get_install_env()
            assert env["PLAYWRIGHT_DOWNLOAD_HOST"] == "https://custom.mirror"
            assert "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST" not in env

    def test_user_set_empty_string_triggers_probe(self) -> None:
        with (
            patch.dict("os.environ", {"PLAYWRIGHT_DOWNLOAD_HOST": ""}, clear=False),
            patch("urllib.request.urlopen", return_value=MagicMock()),
        ):
            env = _get_install_env()
            assert env.get("PLAYWRIGHT_DOWNLOAD_HOST") == ""

    def test_cdn_reachable_no_mirror(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=False),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            _clear_user_env()
            mock_urlopen.return_value = MagicMock()
            env = _get_install_env()
            assert "PLAYWRIGHT_DOWNLOAD_HOST" not in env
            assert "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST" not in env

    def test_cdn_returns_http_400_still_reachable(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=False),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            _clear_user_env()
            mock_urlopen.side_effect = urllib.error.HTTPError(
                _CDN_PROBE_URL, 400, "Bad Request", {}, None
            )
            env = _get_install_env()
            assert "PLAYWRIGHT_DOWNLOAD_HOST" not in env
            assert "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST" not in env

    def test_cdn_returns_http_500_still_reachable(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=False),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            _clear_user_env()
            mock_urlopen.side_effect = urllib.error.HTTPError(
                _CDN_PROBE_URL, 500, "Internal Server Error", {}, None
            )
            env = _get_install_env()
            assert "PLAYWRIGHT_DOWNLOAD_HOST" not in env

    def test_cdn_unreachable_sets_mirror(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=False),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            _clear_user_env()
            mock_urlopen.side_effect = TimeoutError("Connection timed out")
            env = _get_install_env()
            assert env["PLAYWRIGHT_DOWNLOAD_HOST"] == _CN_MIRROR_HOST
            assert env["PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST"] == _CN_MIRROR_CHROMIUM_HOST

    def test_cdn_dns_failure_sets_mirror(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=False),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            _clear_user_env()
            mock_urlopen.side_effect = OSError("Name or service not known")
            env = _get_install_env()
            assert env["PLAYWRIGHT_DOWNLOAD_HOST"] == _CN_MIRROR_HOST

    def test_cdn_url_error_sets_mirror(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=False),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            _clear_user_env()
            mock_urlopen.side_effect = urllib.error.URLError("DNS resolution failed")
            env = _get_install_env()
            assert env["PLAYWRIGHT_DOWNLOAD_HOST"] == _CN_MIRROR_HOST

    def test_cdn_ssl_error_sets_mirror(self) -> None:
        import ssl

        with (
            patch.dict("os.environ", {}, clear=False),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            _clear_user_env()
            mock_urlopen.side_effect = ssl.SSLError("certificate verify failed")
            env = _get_install_env()
            assert env["PLAYWRIGHT_DOWNLOAD_HOST"] == _CN_MIRROR_HOST

    def test_cdn_connection_refused_sets_mirror(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=False),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            _clear_user_env()
            mock_urlopen.side_effect = ConnectionRefusedError()
            env = _get_install_env()
            assert env["PLAYWRIGHT_DOWNLOAD_HOST"] == _CN_MIRROR_HOST

    def test_returns_copy_not_original(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            _clear_user_env()
            with patch("urllib.request.urlopen", return_value=MagicMock()):
                env = _get_install_env()
            import os

            assert env is not os.environ


class TestBuildInstallFailureMessage:
    """Tests for _build_install_failure_message() mirror hint."""

    def test_contains_mirror_hint(self) -> None:
        msg = _build_install_failure_message(RuntimeError("test"))
        assert _CN_MIRROR_HOST in msg
        assert "PLAYWRIGHT_DOWNLOAD_HOST" in msg

    def test_contains_manual_command(self) -> None:
        msg = _build_install_failure_message(RuntimeError("test"))
        assert "patchright install chromium" in msg

    def test_contains_common_causes(self) -> None:
        msg = _build_install_failure_message(RuntimeError("test"))
        assert "Insufficient disk space" in msg

    def test_contains_original_error(self) -> None:
        err = RuntimeError("executable doesn't exist at /usr/lib/chromium")
        msg = _build_install_failure_message(err)
        assert "executable doesn't exist" in msg

    def test_mentions_mainland_china(self) -> None:
        msg = _build_install_failure_message(RuntimeError("test"))
        assert "mainland China" in msg or "china" in msg.lower()


class TestAutoInstallChromium:
    """Tests for _auto_install_chromium — cooldown, failure, integration."""

    @pytest.fixture(autouse=True)
    def _reset_module_state(self) -> None:  # type: ignore[return]
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        old_failure = mod._last_install_failure_at
        old_lock = mod._install_lock
        mod._last_install_failure_at = 0.0
        mod._install_lock = None
        yield
        mod._last_install_failure_at = old_failure
        mod._install_lock = old_lock

    @pytest.mark.asyncio
    async def test_calls_get_install_env_and_passes_to_subprocess(self) -> None:
        from unittest.mock import AsyncMock

        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as launcher_mod

        mock_env = {"PATH": "/usr/bin", "PLAYWRIGHT_DOWNLOAD_HOST": "https://test.mirror"}
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        with (
            patch.object(launcher_mod, "_get_install_env", return_value=mock_env) as mock_get_env,
            patch("asyncio.create_subprocess_exec", return_value=fake_proc) as mock_exec,
        ):
            result = await launcher_mod._auto_install_chromium()

        mock_get_env.assert_called_once()
        assert result is True
        assert mock_exec.call_args.kwargs.get("env") == mock_env

    @pytest.mark.asyncio
    async def test_cooldown_skips_second_attempt(self) -> None:
        import time

        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as launcher_mod

        launcher_mod._last_install_failure_at = time.monotonic()
        result = await launcher_mod._auto_install_chromium()
        assert result is False

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_returns_false(self) -> None:
        from unittest.mock import AsyncMock

        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as launcher_mod

        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.communicate = AsyncMock(return_value=(b"", b"error"))

        with (
            patch.object(launcher_mod, "_get_install_env", return_value={}),
            patch("asyncio.create_subprocess_exec", return_value=fake_proc),
        ):
            result = await launcher_mod._auto_install_chromium()
        assert result is False
        assert launcher_mod._last_install_failure_at > 0

    @pytest.mark.asyncio
    async def test_file_not_found_returns_false(self) -> None:
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as launcher_mod

        with (
            patch.object(launcher_mod, "_get_install_env", return_value={}),
            patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError),
        ):
            result = await launcher_mod._auto_install_chromium()
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self) -> None:
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as launcher_mod

        with (
            patch.object(launcher_mod, "_get_install_env", return_value={}),
            patch("asyncio.create_subprocess_exec", side_effect=TimeoutError),
        ):
            result = await launcher_mod._auto_install_chromium()
        assert result is False


def _clear_user_env() -> None:
    """Remove mirror env vars so tests start clean."""
    import os

    os.environ.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
    os.environ.pop("PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST", None)

"""Unit tests for stealth anti-detection module."""

from __future__ import annotations

import platform

from myrm_agent_harness.toolkits.browser.pool.context_factory import _PLATFORM_UA, _STEALTH_CONTEXT_OPTIONS
from myrm_agent_harness.toolkits.browser.pool.stealth import get_stealth_script


class TestGetStealthScript:
    """Test get_stealth_script() loader."""

    def test_returns_non_empty_string(self) -> None:
        script = get_stealth_script()
        assert isinstance(script, str)
        assert len(script) > 100

    def test_contains_guard_flag(self) -> None:
        script = get_stealth_script()
        assert "__vx_stealth_applied" in script

    def test_contains_webdriver_patch(self) -> None:
        script = get_stealth_script()
        assert "navigator" in script
        assert "webdriver" in script

    def test_contains_plugins_patch(self) -> None:
        script = get_stealth_script()
        assert "plugins" in script
        assert "PDF Viewer" in script

    def test_contains_tostring_disguise(self) -> None:
        script = get_stealth_script()
        assert "WeakMap" in script
        assert "_disguise" in script

    def test_contains_anti_debugger(self) -> None:
        script = get_stealth_script()
        assert "debugger" in script.lower()
        assert "_cleanDebugger" in script

    def test_contains_performance_cleanup(self) -> None:
        script = get_stealth_script()
        assert "Performance.prototype.getEntries" in script

    def test_contains_iframe_chrome_patch(self) -> None:
        script = get_stealth_script()
        assert "HTMLIFrameElement" in script
        assert "contentWindow" in script

    def test_caches_result(self) -> None:
        first = get_stealth_script()
        second = get_stealth_script()
        assert first is second


class TestStealthContextOptions:
    """Test STEALTH context User-Agent platform matching."""

    def test_ua_matches_current_platform(self) -> None:
        ua = str(_STEALTH_CONTEXT_OPTIONS["user_agent"])
        system = platform.system()
        if system == "Darwin":
            assert "Macintosh" in ua
        elif system == "Linux":
            assert "X11; Linux" in ua
        elif system == "Windows":
            assert "Windows NT" in ua

    def test_all_platforms_have_ua(self) -> None:
        for os_name in ("Darwin", "Linux", "Windows"):
            assert os_name in _PLATFORM_UA
            assert "Chrome/" in _PLATFORM_UA[os_name]

    def test_ua_contains_chrome_version(self) -> None:
        ua = str(_STEALTH_CONTEXT_OPTIONS["user_agent"])
        assert "Chrome/147" in ua

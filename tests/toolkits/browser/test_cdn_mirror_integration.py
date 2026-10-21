"""Integration tests for CDN mirror fallback — real network, no mocks.

These tests verify that the CDN probe logic works correctly against the
real cdn.playwright.dev endpoint. They require network access but are
designed to complete quickly (≤10s total).
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.browser.pool.browser_launcher import (
    _CDN_PROBE_URL,
    _CN_MIRROR_HOST,
    _get_install_env,
)


@pytest.mark.timeout(15)
class TestCdnProbeRealNetwork:
    """Real-network integration tests for _get_install_env()."""

    def test_real_cdn_probe_returns_valid_env(self) -> None:
        """Verify _get_install_env returns a usable env dict with real probe."""
        _clear_mirror_env()
        env = _get_install_env()

        assert isinstance(env, dict)
        assert "PATH" in env

        # Env must be passable to subprocess — all keys and values must be strings
        for k, v in env.items():
            assert isinstance(k, str), f"key {k!r} is not str"
            assert isinstance(v, str), f"value for {k!r} is not str"

    def test_real_cdn_probe_consistent_results(self) -> None:
        """Two consecutive calls should produce the same mirror decision."""
        _clear_mirror_env()
        env1 = _get_install_env()
        env2 = _get_install_env()

        has_mirror_1 = "PLAYWRIGHT_DOWNLOAD_HOST" in env1
        has_mirror_2 = "PLAYWRIGHT_DOWNLOAD_HOST" in env2
        assert has_mirror_1 == has_mirror_2, "Inconsistent CDN probe results"

    def test_user_env_override_respected_in_real_network(self) -> None:
        """User-set PLAYWRIGHT_DOWNLOAD_HOST should bypass real probe entirely."""
        custom_host = "https://my-custom-mirror.example.com"
        with patch.dict(os.environ, {"PLAYWRIGHT_DOWNLOAD_HOST": custom_host}):
            env = _get_install_env()
            assert env["PLAYWRIGHT_DOWNLOAD_HOST"] == custom_host
            assert "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST" not in env

    def test_env_does_not_mutate_os_environ(self) -> None:
        """_get_install_env must not modify os.environ regardless of CDN state."""
        _clear_mirror_env()
        original_keys = set(os.environ.keys())
        _get_install_env()
        current_keys = set(os.environ.keys())
        assert "PLAYWRIGHT_DOWNLOAD_HOST" not in os.environ
        assert original_keys == current_keys, "os.environ was mutated"

    def test_mirror_urls_are_valid_https(self) -> None:
        """If mirror is set, URLs must be valid HTTPS endpoints."""
        _clear_mirror_env()
        env = _get_install_env()
        if "PLAYWRIGHT_DOWNLOAD_HOST" in env:
            assert env["PLAYWRIGHT_DOWNLOAD_HOST"].startswith("https://")
            assert env["PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST"].startswith("https://")

    def test_cdn_probe_url_is_https(self) -> None:
        """Sanity check: probe URL must be HTTPS."""
        assert _CDN_PROBE_URL.startswith("https://")

    def test_mirror_host_matches_expected(self) -> None:
        """Sanity check: mirror host constant is npmmirror."""
        assert "npmmirror" in _CN_MIRROR_HOST


def _clear_mirror_env() -> None:
    os.environ.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
    os.environ.pop("PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST", None)

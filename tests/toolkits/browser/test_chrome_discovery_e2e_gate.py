"""Tests for chrome_discovery E2E port gating."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.browser.pool import chrome_discovery


def test_e2e_port_skipped_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYRM_CHROME_E2E", raising=False)

    def probe(port: int) -> bool:
        return port == 9333

    with patch.object(chrome_discovery, "_probe_http_version", side_effect=probe):
        with patch.object(chrome_discovery, "get_chromium_data_dirs", return_value=iter([])):
            endpoint = chrome_discovery.discover_chrome_cdp_endpoint()
    assert endpoint is None


def test_e2e_port_used_when_env_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYRM_CHROME_E2E", "1")
    with patch.object(chrome_discovery, "_myrm_e2e_port", return_value=9333):
        with patch.object(chrome_discovery, "_probe_http_version", return_value=True) as probe:
            endpoint = chrome_discovery.discover_chrome_cdp_endpoint()
    assert endpoint == "http://127.0.0.1:9333"
    probe.assert_called_once_with(9333)

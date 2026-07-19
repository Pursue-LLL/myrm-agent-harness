"""Unit tests for Camoufox launch env sanitization helper."""

from __future__ import annotations

from unittest.mock import patch

from myrm_agent_harness.toolkits.browser.pool.browser_launcher import _camoufox_launch_env


def test_camoufox_launch_env_sanitizes_host_and_preserves_fingerprint_keys() -> None:
    host_env = {
        "PATH": "/usr/bin",
        "AWS_SECRET_ACCESS_KEY": "leak-me",
        "MOZ_HEADLESS": "0",
    }
    fingerprint_env = {"MOZ_HEADLESS": "1", "CAMOUFOX_FINGERPRINT": "abc"}

    with patch(
        "myrm_agent_harness.toolkits.code_execution.security.validator.sanitize_env",
        return_value={"PATH": "/usr/bin"},
    ):
        merged = _camoufox_launch_env(fingerprint_env)

    assert merged["MOZ_HEADLESS"] == "1"
    assert merged["CAMOUFOX_FINGERPRINT"] == "abc"
    assert merged["PATH"] == "/usr/bin"
    assert "AWS_SECRET_ACCESS_KEY" not in merged


def test_camoufox_launch_env_without_fingerprint_uses_sanitize_only() -> None:
    with patch(
        "myrm_agent_harness.toolkits.code_execution.security.validator.sanitize_env",
        return_value={"PATH": "/bin"},
    ) as mock_sanitize:
        merged = _camoufox_launch_env(None)

    mock_sanitize.assert_called_once()
    assert merged == {"PATH": "/bin"}

"""Unit tests for the browser doctor extension relay check."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.doctor import CheckStatus
from myrm_agent_harness.toolkits.browser.doctor.checks import _check_extension_relay


async def test_check_extension_relay_requires_access_policy() -> None:
    """Relay ready without domains must not report OK."""
    import json

    payload = json.dumps(
        {
            "relay_cdp_ready": True,
            "access_policy_valid": False,
            "auth_token_required": False,
            "auth_token_configured": True,
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = payload
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "access policy" in result.message.lower()
    assert result.fix is not None
    assert not (result.details or {}).get("optional")


async def test_check_extension_relay_ok_when_policy_valid() -> None:
    """Relay and access policy both ready should report OK."""
    import json

    payload = json.dumps(
        {
            "relay_cdp_ready": True,
            "access_policy_valid": True,
            "auth_token_required": False,
            "auth_token_configured": True,
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = payload
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.OK


async def test_check_extension_relay_non_dict_payload_graceful() -> None:
    """Non-dict JSON (e.g. gateway swallowing the endpoint) must degrade, not crash."""

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "[]"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "unexpected response format" in result.message.lower()
    assert result.fix is not None


@pytest.mark.asyncio
async def test_check_extension_relay_uses_custom_base_url() -> None:
    """An explicit base URL must drive the probe target, overriding defaults."""
    import json

    payload = json.dumps(
        {
            "relay_cdp_ready": True,
            "access_policy_valid": True,
            "auth_token_required": False,
            "auth_token_configured": True,
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = payload
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay(base_url="http://127.0.0.1:18080")

    assert result.status == CheckStatus.OK
    mock_client.get.assert_awaited_once_with("http://127.0.0.1:18080/api/v1/extension/setup-hints")


@pytest.mark.asyncio
async def test_check_extension_relay_non_http_scheme() -> None:
    """Relay probe rejects non-http base URLs from the environment."""

    with patch.dict(os.environ, {"MYRM_SERVER_URL": "ftp://localhost:8080"}):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "http(s) scheme" in result.message
    assert not (result.details or {}).get("optional")


@pytest.mark.asyncio
async def test_check_extension_relay_connection_error() -> None:
    """Relay probe degrades to WARNING when the server is unreachable."""
    import httpx

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.side_effect = httpx.ConnectError("connection refused")

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "Server unreachable" in result.message
    assert not (result.details or {}).get("optional")


@pytest.mark.asyncio
async def test_check_extension_relay_probe_failure() -> None:
    """Relay probe reports unexpected failures with the exception detail."""

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.side_effect = RuntimeError("boom")

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "probe failed" in result.message.lower()
    assert "boom" in result.message
    assert not (result.details or {}).get("optional")


@pytest.mark.asyncio
async def test_check_extension_relay_auth_token_missing() -> None:
    """Relay probe warns when the server requires an unconfigured auth token."""
    import json

    payload = json.dumps(
        {
            "relay_cdp_ready": False,
            "access_policy_valid": False,
            "auth_token_required": True,
            "auth_token_configured": False,
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = payload
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "auth token missing" in result.message
    assert not (result.details or {}).get("optional")


@pytest.mark.asyncio
async def test_check_extension_relay_not_connected() -> None:
    """Relay probe warns when the extension is not connected at all."""
    import json

    payload = json.dumps(
        {
            "relay_cdp_ready": False,
            "access_policy_valid": False,
            "auth_token_required": False,
            "auth_token_configured": False,
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = payload
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.checks.create_httpx_client",
        return_value=mock_client,
    ):
        result = await _check_extension_relay()

    assert result.status == CheckStatus.WARNING
    assert "not connected" in result.message
    assert result.details == {"optional": True}

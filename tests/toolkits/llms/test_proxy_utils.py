"""Unit tests for proxy validation, masking, and health probe utilities."""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.llms.utils.proxy import (
    mask_proxy_url,
    probe_proxy_health,
    validate_proxy_url,
)


def test_mask_proxy_url() -> None:
    assert mask_proxy_url(None) is None
    assert mask_proxy_url("") == ""
    assert mask_proxy_url("   ") == ""

    # URL without credentials
    assert mask_proxy_url("http://127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert mask_proxy_url("socks5://proxy.example.com:1080") == "socks5://proxy.example.com:1080"

    # URL with credentials
    assert (
        mask_proxy_url("http://user:supersecret@127.0.0.1:7890")
        == "http://user:***@127.0.0.1:7890"
    )
    assert (
        mask_proxy_url("socks5://admin:p@ssw0rd!@gateway.corp.internal:1080/subpath")
        == "socks5://admin:***@gateway.corp.internal:1080/subpath"
    )


def test_validate_proxy_url() -> None:
    # Empty / None rejected by validator
    assert validate_proxy_url(None) == (False, "Proxy URL cannot be empty")
    assert validate_proxy_url("") == (False, "Proxy URL cannot be empty")
    assert validate_proxy_url("   ") == (False, "Proxy URL cannot be empty")

    # Valid schemes
    assert validate_proxy_url("http://127.0.0.1:7890")[0] is True
    assert validate_proxy_url("https://secure-proxy.org:8443")[0] is True
    assert validate_proxy_url("socks5://user:pass@192.168.1.10:1080")[0] is True
    assert validate_proxy_url("socks5h://localhost:9050")[0] is True

    # Invalid schemes
    is_valid, err = validate_proxy_url("ftp://proxy.example.com:21")
    assert is_valid is False
    assert err is not None and "Unsupported proxy scheme" in err

    is_valid, err = validate_proxy_url("ws://proxy.example.com:80")
    assert is_valid is False
    assert err is not None and "Unsupported proxy scheme" in err

    # Missing host / malformed
    is_valid, err = validate_proxy_url("http://")
    assert is_valid is False
    assert err is not None and "missing hostname" in err.lower()

    is_valid, err = validate_proxy_url("not-a-url")
    assert is_valid is False

    # Blocked link-local and metadata addresses
    is_valid, err = validate_proxy_url("http://169.254.169.254:80")
    assert is_valid is False
    assert err is not None and "link-local" in err.lower()

    is_valid, err = validate_proxy_url("http://169.254.1.1:8080")
    assert is_valid is False
    assert err is not None and "link-local" in err.lower()

    is_valid, err = validate_proxy_url("http://[fe80::1]:8080")
    assert is_valid is False
    assert err is not None and "link-local" in err.lower()

    is_valid, err = validate_proxy_url("http://[::ffff:169.254.169.254]:8080")
    assert is_valid is False
    assert err is not None and "link-local" in err.lower()

    is_valid, err = validate_proxy_url("http://0.0.0.0:8080")
    assert is_valid is False
    assert err is not None and "unspecified" in err.lower()

    is_valid, err = validate_proxy_url("http://instance-data:80")
    assert is_valid is False
    assert err is not None and "metadata" in err.lower()

    is_valid, err = validate_proxy_url("http://metadata.google.internal:80")
    assert is_valid is False
    assert err is not None and "metadata" in err.lower()


@pytest.mark.asyncio
async def test_probe_proxy_health_success() -> None:
    mock_resp = AsyncMock()
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.return_value = mock_resp
        ok, err = await probe_proxy_health("http://127.0.0.1:7890", target_url="https://1.1.1.1")
        assert ok is True
        assert err is None


@pytest.mark.asyncio
async def test_probe_proxy_health_invalid_url() -> None:
    ok, err = await probe_proxy_health("ftp://invalid:21")
    assert ok is False
    assert err is not None and "Unsupported proxy scheme" in err


@pytest.mark.asyncio
async def test_probe_proxy_health_network_failure() -> None:
    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.side_effect = ConnectionRefusedError("Connection refused by proxy")
        ok, err = await probe_proxy_health("http://127.0.0.1:9999", target_url="https://1.1.1.1")
        assert ok is False
        assert err is not None and "Connection refused by proxy" in err


@pytest.mark.asyncio
async def test_probe_proxy_health_blocked_addresses() -> None:
    ok, err = await probe_proxy_health("http://169.254.169.254:80")
    assert ok is False
    assert err is not None and "link-local" in err.lower()

    ok, err = await probe_proxy_health("http://metadata.google.internal:80")
    assert ok is False
    assert err is not None and "metadata" in err.lower()


@pytest.mark.asyncio
async def test_probe_proxy_health_blocked_target() -> None:
    ok, err = await probe_proxy_health(
        "http://127.0.0.1:7890",
        target_url="http://169.254.169.254/latest/meta-data/",
    )
    assert ok is False
    assert err is not None and "probe target url blocked" in err.lower()


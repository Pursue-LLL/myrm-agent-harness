"""Unit tests for proxy validation, masking, and health probe utilities."""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.llms.utils.proxy import (
    clear_proxy_probe_cache,
    mask_proxy_url,
    normalize_proxy_url,
    probe_proxy_health,
    validate_proxy_url,
)


@pytest.fixture(autouse=True)
def _reset_probe_cache() -> None:
    clear_proxy_probe_cache()
    yield
    clear_proxy_probe_cache()


def test_normalize_proxy_url() -> None:
    assert normalize_proxy_url(None) is None
    assert normalize_proxy_url("") is None
    assert normalize_proxy_url("   ") is None

    # Rewrites socks:// to socks5://
    assert normalize_proxy_url("socks://127.0.0.1:1080") == "socks5://127.0.0.1:1080"
    assert normalize_proxy_url("SOCKS://127.0.0.1:1080") == "socks5://127.0.0.1:1080"
    assert (
        normalize_proxy_url("  socks://user:pass@proxy.corp:1080  ")
        == "socks5://user:pass@proxy.corp:1080"
    )

    # Leaves standard schemes untouched
    assert normalize_proxy_url("http://127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert normalize_proxy_url("https://127.0.0.1:7890") == "https://127.0.0.1:7890"
    assert normalize_proxy_url("socks5://127.0.0.1:1080") == "socks5://127.0.0.1:1080"
    assert normalize_proxy_url("socks5h://127.0.0.1:1080") == "socks5h://127.0.0.1:1080"


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

    # Embedded URLs in text messages
    assert (
        mask_proxy_url("Connection to http://user:secret@10.0.0.1:8080 failed")
        == "Connection to http://user:***@10.0.0.1:8080 failed"
    )
    assert (
        mask_proxy_url("Multiple: http://a:b@host1:80 and socks5://c:d@host2:1080")
        == "Multiple: http://a:***@host1:80 and socks5://c:***@host2:1080"
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
    assert validate_proxy_url("socks://127.0.0.1:1080")[0] is True
    assert validate_proxy_url("socks://user:pass@192.168.1.10:1080")[0] is True
    assert validate_proxy_url("SOCKS://localhost:1080")[0] is True

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


@pytest.mark.asyncio
async def test_probe_proxy_health_auth_required() -> None:
    mock_resp = AsyncMock()
    mock_resp.status_code = 407

    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.return_value = mock_resp
        ok, err = await probe_proxy_health("http://127.0.0.1:7890", target_url="https://1.1.1.1")
        assert ok is False
        assert err is not None and "407" in err


@pytest.mark.asyncio
async def test_probe_proxy_health_blocked_or_throttled() -> None:
    for code in (403, 429):
        mock_resp = AsyncMock()
        mock_resp.status_code = code

        with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
            mock_head.return_value = mock_resp
            ok, err = await probe_proxy_health(
                "http://127.0.0.1:7890",
                target_url="https://1.1.1.1",
                cache_ttl_s=0.0,
            )
            assert ok is False
            assert err is not None and str(code) in err


@pytest.mark.asyncio
async def test_probe_proxy_health_upstream_4xx_success() -> None:
    for code in (401, 404, 405):
        mock_resp = AsyncMock()
        mock_resp.status_code = code

        with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
            mock_head.return_value = mock_resp
            ok, err = await probe_proxy_health(
                "http://127.0.0.1:7890",
                target_url="https://api.openai.com/v1",
                cache_ttl_s=0.0,
            )
            assert ok is True
            assert err is None


@pytest.mark.asyncio
async def test_probe_proxy_health_server_error() -> None:
    mock_resp = AsyncMock()
    mock_resp.status_code = 502

    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.return_value = mock_resp
        ok, err = await probe_proxy_health("http://127.0.0.1:7890", target_url="https://1.1.1.1")
        assert ok is False
        assert err is not None and "Proxy or upstream server error (HTTP 502)" in err


@pytest.mark.asyncio
async def test_probe_proxy_health_credential_sanitization() -> None:
    import httpx

    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.side_effect = httpx.ProxyError(
            "Failed connecting to http://myuser:supersecretpass@10.0.0.1:8080: timed out"
        )
        ok, err = await probe_proxy_health(
            "http://myuser:supersecretpass@10.0.0.1:8080",
            target_url="https://1.1.1.1",
            cache_ttl_s=0.0,
        )
        assert ok is False
        assert err is not None
        assert "supersecretpass" not in err
        assert "http://myuser:***@10.0.0.1:8080" in err


@pytest.mark.asyncio
async def test_probe_proxy_health_caching_and_ttl() -> None:
    mock_resp = AsyncMock()
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.return_value = mock_resp

        # First call hits mock
        ok1, err1 = await probe_proxy_health("http://127.0.0.1:7890", cache_ttl_s=60.0)
        assert ok1 is True
        assert err1 is None
        assert mock_head.call_count == 1

        # Second call within TTL hits cache, head is NOT called again
        ok2, err2 = await probe_proxy_health("http://127.0.0.1:7890", cache_ttl_s=60.0)
        assert ok2 is True
        assert err2 is None
        assert mock_head.call_count == 1

        # Clear cache and call again: head IS called again
        clear_proxy_probe_cache()
        ok3, err3 = await probe_proxy_health("http://127.0.0.1:7890", cache_ttl_s=60.0)
        assert ok3 is True
        assert err3 is None
        assert mock_head.call_count == 2



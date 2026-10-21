import time
import urllib.parse
from unittest.mock import AsyncMock, patch

import httpx
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


def test_sanitize_proxy_error_url_encoded_password() -> None:
    from myrm_agent_harness.toolkits.llms.utils.proxy import _sanitize_proxy_error

    raw_proxy = "http://user:p%40ss%3Aword@proxy.domain.com:8080"
    raw_error = "ConnectError to http://user:p%40ss%3Aword@proxy.domain.com:8080 failed"
    sanitized = _sanitize_proxy_error(raw_error, raw_proxy)
    assert "p%40ss%3Aword" not in sanitized
    assert "http://user:***@proxy.domain.com:8080" in sanitized


def test_mask_proxy_url_invalid_url_fallback() -> None:
    with patch("myrm_agent_harness.toolkits.llms.utils.proxy.urlparse", side_effect=ValueError("corrupt netloc")):
        masked = mask_proxy_url("http://user:pass@invalid:99999999")
        assert masked == "<invalid-proxy-url>"


def test_validate_proxy_url_exception_handling() -> None:
    with patch("myrm_agent_harness.toolkits.llms.utils.proxy.urlparse", side_effect=ValueError("bad url structure")):
        is_valid, err = validate_proxy_url("http://bad-proxy:8080")
        assert is_valid is False
        assert err is not None and "Invalid proxy URL" in err


@pytest.mark.asyncio
async def test_probe_proxy_health_edge_cases() -> None:
    # Empty URL
    ok, err = await probe_proxy_health("")
    assert ok is False
    assert err == "Proxy URL cannot be empty"

    # Unsupported target scheme
    ok, err = await probe_proxy_health("http://127.0.0.1:7890", target_url="ftp://ftp.example.com")
    assert ok is False
    assert err is not None and "Unsupported probe target scheme" in err

    # Target URL missing hostname
    ok, err = await probe_proxy_health("http://127.0.0.1:7890", target_url="http://")
    assert ok is False
    assert err is not None and "missing hostname" in err

    # Target URL exception
    orig_urlparse = urllib.parse.urlparse

    def _urlparse_side_effect(url: str, *args: object, **kwargs: object) -> urllib.parse.ParseResult:
        if url == "http://fail-target":
            raise ValueError("bad target")
        return orig_urlparse(url, *args, **kwargs)

    with patch("myrm_agent_harness.toolkits.llms.utils.proxy.urlparse", side_effect=_urlparse_side_effect):
        ok, err = await probe_proxy_health("http://127.0.0.1:7890", target_url="http://fail-target")
        assert ok is False
        assert err is not None and "Invalid probe target URL" in err

    # ConnectTimeout
    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.side_effect = httpx.ConnectTimeout("connection timed out")
        ok, err = await probe_proxy_health("http://127.0.0.1:7890", target_url="https://1.1.1.1", cache_ttl_s=0.0)
        assert ok is False
        assert err == "Proxy connection timed out"

    # Unexpected HTTP status (e.g., 101 Switching Protocols)
    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        resp = AsyncMock()
        resp.status_code = 101
        mock_head.return_value = resp
        ok, err = await probe_proxy_health("http://127.0.0.1:7890", target_url="https://1.1.1.1", cache_ttl_s=0.0)
        assert ok is False
        assert err is not None and "unexpected HTTP 101" in err


@pytest.mark.asyncio
async def test_probe_proxy_health_cache_eviction() -> None:
    from myrm_agent_harness.toolkits.llms.utils.proxy import _PROBE_CACHE_MAX_ENTRIES, _probe_cache

    clear_proxy_probe_cache()
    mock_resp = AsyncMock()
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.return_value = mock_resp

        # Fill cache to capacity with expired entries
        for i in range(_PROBE_CACHE_MAX_ENTRIES):
            _probe_cache[(f"http://127.0.0.1:{10000 + i}", "https://1.1.1.1")] = (
                time.monotonic() - 100.0,
                True,
                None,
            )

        # Probing a new URL triggers eviction of expired entries
        ok, _ = await probe_proxy_health("http://127.0.0.1:9999", target_url="https://1.1.1.1", cache_ttl_s=60.0)
        assert ok is True
        assert ("http://127.0.0.1:9999", "https://1.1.1.1") in _probe_cache




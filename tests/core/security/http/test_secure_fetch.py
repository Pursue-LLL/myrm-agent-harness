"""Architecture and behavior tests for SSRF-protected HTTP fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.core.security.http.secure_fetch import (
    ContentTooLargeError,
    _https_pin_extensions,
    resolve_secure_http_target,
    secure_get,
    secure_request,
)


@pytest.mark.asyncio
async def test_secure_request_blocks_redirect_to_internal() -> None:
    redirect_response = httpx.Response(
        302,
        headers={"Location": "http://192.168.1.1/secret"},
        request=httpx.Request("GET", "https://example.com/start"),
    )

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(
            side_effect=[
                ("https://93.184.216.34/", {"Host": "example.com"}),
                SSRFSecurityError("Blocked IP"),
            ]
        ),
    ):
        transport = httpx.MockTransport(lambda _request: redirect_response)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            with pytest.raises(SSRFSecurityError):
                await secure_request(client, "GET", "https://example.com/start")


@pytest.mark.asyncio
async def test_secure_request_follows_safe_redirect() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                302,
                headers={"Location": "https://example.com/final"},
                request=request,
            )
        return httpx.Response(200, text="ok", request=request)

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(
            side_effect=[
                ("https://93.184.216.34/", {"Host": "example.com"}),
                ("https://93.184.216.34/final", {"Host": "example.com"}),
            ]
        ),
    ):
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            response = await secure_request(client, "GET", "https://example.com/start")
            assert response.status_code == 200
            assert response.text == "ok"
            assert call_count == 2


@pytest.mark.asyncio
async def test_resolve_secure_http_target_returns_pinned_final_hop() -> None:
    redirect_response = httpx.Response(
        302,
        headers={"Location": "https://example.com/final"},
        request=httpx.Request("GET", "https://example.com/start"),
    )
    final_response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/final"),
    )
    responses = [redirect_response, final_response]

    def handler(_request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(
            side_effect=[
                ("https://1.2.3.4/", {"Host": "example.com"}),
                ("https://5.6.7.8/final", {"Host": "example.com"}),
            ]
        ),
    ):
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            target = await resolve_secure_http_target(client, "https://example.com/start")
            assert target.logical_url == "https://example.com/final"
            assert target.request_url == "https://5.6.7.8/final"
            assert target.headers["Host"] == "example.com"


@pytest.mark.asyncio
async def test_secure_get_reads_response_body() -> None:
    mock_response = httpx.Response(
        200,
        text="payload",
        request=httpx.Request("GET", "https://example.com"),
    )
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_request",
        new=AsyncMock(return_value=mock_response),
    ) as mock_secure_request:
        response = await secure_get("https://example.com")
        assert response.text == "payload"
        mock_secure_request.assert_awaited_once()


def test_https_pin_extensions_sets_sni_for_pinned_https_ip() -> None:
    extensions = _https_pin_extensions(
        "https://93.184.216.34/zen/go/v1/models",
        {"Host": "opencode.ai"},
    )
    assert extensions == {"sni_hostname": "opencode.ai"}


def test_https_pin_extensions_skips_non_ip_and_http() -> None:
    assert _https_pin_extensions("https://opencode.ai/v1/models", {"Host": "opencode.ai"}) == {}
    assert _https_pin_extensions("http://93.184.216.34/v1/models", {"Host": "opencode.ai"}) == {}
    assert _https_pin_extensions("https://93.184.216.34/v1/models", {}) == {}


@pytest.mark.asyncio
async def test_secure_request_passes_sni_extensions_for_pinned_https_ip() -> None:
    captured_extensions: list[dict[str, object]] = []

    async def _capture_send(request: httpx.Request, **_kwargs: object) -> httpx.Response:
        captured_extensions.append(dict(request.extensions))
        return httpx.Response(200, text="ok", request=request)

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(
            return_value=("https://93.184.216.34/zen/go/v1/models", {"Host": "opencode.ai"}),
        ),
    ):
        client = AsyncMock()
        client.build_request = httpx.AsyncClient().build_request
        client.send = AsyncMock(side_effect=_capture_send)
        response = await secure_request(client, "GET", "https://opencode.ai/zen/go/v1/models")
        assert response.status_code == 200
        assert len(captured_extensions) == 1
        assert captured_extensions[0]["sni_hostname"] == "opencode.ai"


@pytest.mark.asyncio
async def test_secure_request_raises_when_content_length_exceeds_limit() -> None:
    """A Content-Length over the limit is rejected before the body is downloaded."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "1000"},
            content=b"x" * 1000,
            request=request,
        )

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(return_value=("https://example.com/", {"Host": "example.com"})),
    ):
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            with pytest.raises(ContentTooLargeError):
                await secure_request(
                    client, "GET", "https://example.com", max_content_length=100
                )


@pytest.mark.asyncio
async def test_secure_request_raises_when_stream_exceeds_limit() -> None:
    """Bodies without a usable Content-Length are aborted mid-stream when oversized."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"y" * 500),
            request=request,
        )

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(return_value=("https://example.com/", {"Host": "example.com"})),
    ):
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            with pytest.raises(ContentTooLargeError):
                await secure_request(
                    client, "GET", "https://example.com", max_content_length=100
                )


@pytest.mark.asyncio
async def test_secure_request_returns_full_body_without_limit() -> None:
    """Passing max_content_length=None disables the cap (opt-out, backwards compatible)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"z" * 500, request=request)

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(return_value=("https://example.com/", {"Host": "example.com"})),
    ):
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            response = await secure_request(
                client, "GET", "https://example.com", max_content_length=None
            )
            assert len(response.content) == 500


@pytest.mark.asyncio
async def test_secure_request_applies_default_cap() -> None:
    """The secure-by-default cap rejects a body whose Content-Length exceeds it."""
    from myrm_agent_harness.core.security.http.secure_fetch import (
        DEFAULT_MAX_CONTENT_LENGTH,
    )

    oversized = DEFAULT_MAX_CONTENT_LENGTH + 1

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(oversized)},
            content=b"x" * oversized,
            request=request,
        )

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(return_value=("https://example.com/", {"Host": "example.com"})),
    ):
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            with pytest.raises(ContentTooLargeError):
                await secure_request(client, "GET", "https://example.com")


@pytest.mark.asyncio
async def test_secure_get_passes_max_content_length() -> None:
    mock_response = httpx.Response(
        200,
        content=b"payload",
        request=httpx.Request("GET", "https://example.com"),
    )
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_request",
        new=AsyncMock(return_value=mock_response),
    ) as mock_secure_request:
        await secure_get("https://example.com", max_content_length=42)
        assert mock_secure_request.await_args.kwargs["max_content_length"] == 42


@pytest.mark.asyncio
async def test_resolve_target_no_redirects_with_negative_limit() -> None:
    """Negative max_redirects exits the loop immediately, hitting the guard raise."""

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(return_value=("https://93.184.216.34/", {"Host": "example.com"})),
    ):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text="ok", request=req)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(SSRFSecurityError, match="Too many redirects"):
                await resolve_secure_http_target(
                    client, "https://example.com/start", max_redirects=-1
                )


@ pytest.mark.asyncio
async def test_secure_request_disables_shield_passthrough() -> None:
    """enable_ssrf_shield=False short-circuits DNS pinning entirely."""
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(),
    ) as mock_pin:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text="ok", request=req)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await secure_request(
                client, "GET", "https://example.com", enable_ssrf_shield=False
            )
            assert resp.status_code == 200
        mock_pin.assert_not_called()


@ pytest.mark.asyncio
async def test_secure_request_redirect_downgrades_post_to_get() -> None:
    """301 with a body-capable method downgrades the next hop to GET."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(301, headers={"Location": "/final"}, request=request)
        assert request.method == "GET"
        return httpx.Response(200, text="done", request=request)

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(
            side_effect=[
                ("https://example.com/start", {}),
                ("https://example.com/final", {}),
            ]
        ),
    ):
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            resp = await secure_request(client, "POST", "https://example.com/start")
            assert resp.status_code == 200
            assert resp.text == "done"


def test_https_pin_extensions_empty_hop_host() -> None:
    assert _https_pin_extensions("https:///bare", {"Host": "example.com"}) == {}


@ pytest.mark.asyncio
async def test_resolve_target_ssrf_blocked_during_redirect() -> None:
    redirect_response = httpx.Response(
        302,
        headers={"Location": "https://example.com/final"},
        request=httpx.Request("GET", "https://example.com/start"),
    )
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(
            side_effect=[
                ("https://93.184.216.34/", {"Host": "example.com"}),
                SSRFSecurityError("Blocked during redirect"),
            ]
        ),
    ):
        transport = httpx.MockTransport(lambda _req: redirect_response)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(SSRFSecurityError, match="Blocked during redirect"):
                await resolve_secure_http_target(client, "https://example.com/start")


@ pytest.mark.asyncio
async def test_resolve_target_too_many_redirects() -> None:
    redirect_response = httpx.Response(
        302,
        headers={"Location": "https://example.com/final"},
        request=httpx.Request("GET", "https://example.com/start"),
    )
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(return_value=("https://93.184.216.34/", {"Host": "example.com"})),
    ):
        transport = httpx.MockTransport(lambda _req: redirect_response)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(SSRFSecurityError, match="Too many redirects"):
                await resolve_secure_http_target(
                    client, "https://example.com/start", max_redirects=0
                )


@ pytest.mark.asyncio
async def test_secure_request_too_many_redirects() -> None:
    redirect_response = httpx.Response(
        302,
        headers={"Location": "https://example.com/final"},
        request=httpx.Request("GET", "https://example.com/start"),
    )
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(return_value=("https://93.184.216.34/", {"Host": "example.com"})),
    ):
        transport = httpx.MockTransport(lambda _req: redirect_response)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(SSRFSecurityError, match="Too many redirects"):
                await secure_request(
                    client, "GET", "https://example.com/start", max_redirects=0
                )


@ pytest.mark.asyncio
async def test_secure_request_no_response_received() -> None:
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        new=AsyncMock(return_value=("https://example.com/", {})),
    ):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text="ok", request=req)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError, match="No response received"):
                await secure_request(
                    client, "GET", "https://example.com", max_redirects=-1
                )

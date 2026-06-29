"""Architecture and behavior tests for SSRF-protected HTTP fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.core.security.http.secure_fetch import (
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

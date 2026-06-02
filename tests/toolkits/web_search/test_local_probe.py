"""Tests for local search probe utilities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from myrm_agent_harness.toolkits.web_search.local_probe import (
    probe_local_search_services,
    probe_searxng_endpoints,
)


def _mock_client(get_side_effect: object) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=get_side_effect)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


async def _searxng_success_get(url: str, **_kwargs: object) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    if "search?" in url:
        response.text = '<article class="result"><a href="https://example.com">x</a></article>'
    else:
        response.text = "ok"
    return response


@pytest.mark.asyncio
async def test_probe_searxng_first_url_success() -> None:
    with patch(
        "myrm_agent_harness.toolkits.web_search.local_probe.httpx.AsyncClient",
        return_value=_mock_client(_searxng_success_get),
    ):
        result = await probe_searxng_endpoints(("http://127.0.0.1:8081",))

    assert result.available is True
    assert result.base_url == "http://127.0.0.1:8081"


@pytest.mark.asyncio
async def test_probe_searxng_fallback_to_second_url() -> None:
    urls = ("http://127.0.0.1:8081", "http://127.0.0.1:8082")

    async def mock_get(url: str, **_kwargs: object) -> MagicMock:
        response = MagicMock()
        if url.startswith("http://127.0.0.1:8081"):
            raise OSError("connection refused")
        response.status_code = 200
        if "search?" in url:
            response.text = '<div id="results"><article class="result"></article></div>'
        else:
            response.text = "ok"
        return response

    with patch(
        "myrm_agent_harness.toolkits.web_search.local_probe.httpx.AsyncClient",
        return_value=_mock_client(mock_get),
    ):
        result = await probe_searxng_endpoints(urls)

    assert result.available is True
    assert result.base_url == "http://127.0.0.1:8082"


@pytest.mark.asyncio
async def test_probe_searxng_ping_ok_search_empty() -> None:
    async def mock_get(url: str, **_kwargs: object) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.text = "empty page" if "search?" in url else "ok"
        return response

    with patch(
        "myrm_agent_harness.toolkits.web_search.local_probe.httpx.AsyncClient",
        return_value=_mock_client(mock_get),
    ):
        result = await probe_searxng_endpoints(("http://127.0.0.1:8081",))

    assert result.available is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_probe_searxng_ping_http_500() -> None:
    async def mock_get(_url: str, **_kwargs: object) -> MagicMock:
        response = MagicMock()
        response.status_code = 500
        response.text = "error"
        return response

    with patch(
        "myrm_agent_harness.toolkits.web_search.local_probe.httpx.AsyncClient",
        return_value=_mock_client(mock_get),
    ):
        result = await probe_searxng_endpoints(("http://127.0.0.1:8081",))

    assert result.available is False


@pytest.mark.asyncio
async def test_probe_searxng_search_http_500() -> None:
    async def mock_get(url: str, **_kwargs: object) -> MagicMock:
        response = MagicMock()
        if "search?" in url:
            response.status_code = 503
            response.text = "unavailable"
        else:
            response.status_code = 200
            response.text = "ok"
        return response

    with patch(
        "myrm_agent_harness.toolkits.web_search.local_probe.httpx.AsyncClient",
        return_value=_mock_client(mock_get),
    ):
        result = await probe_searxng_endpoints(("http://127.0.0.1:8081",))

    assert result.available is False


@pytest.mark.asyncio
async def test_probe_searxng_verify_connection_error() -> None:
    call_count = 0

    async def mock_get(url: str, **_kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if "search?" in url:
            raise httpx.ConnectError("refused", request=httpx.Request("GET", url))
        response = MagicMock()
        response.status_code = 200
        response.text = "ok"
        return response

    with patch(
        "myrm_agent_harness.toolkits.web_search.local_probe.httpx.AsyncClient",
        return_value=_mock_client(mock_get),
    ):
        result = await probe_searxng_endpoints(("http://127.0.0.1:8081",))

    assert result.available is False
    assert call_count == 2


@pytest.mark.asyncio
async def test_probe_searxng_all_fail() -> None:
    with patch(
        "myrm_agent_harness.toolkits.web_search.local_probe.httpx.AsyncClient",
        return_value=_mock_client(OSError("connection refused")),
    ):
        result = await probe_searxng_endpoints(("http://127.0.0.1:8081",))

    assert result.available is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_probe_local_search_services_delegates_to_searxng() -> None:
    with patch(
        "myrm_agent_harness.toolkits.web_search.local_probe.probe_searxng_endpoints",
        return_value=MagicMock(provider="searxng", available=True, base_url="http://127.0.0.1:8081"),
    ) as mock_probe:
        results = await probe_local_search_services()

    assert len(results) == 1
    assert results[0].provider == "searxng"
    mock_probe.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_local_search_services_searxng_exception() -> None:
    with patch(
        "myrm_agent_harness.toolkits.web_search.local_probe.probe_searxng_endpoints",
        side_effect=RuntimeError("searxng crash"),
    ):
        results = await probe_local_search_services()

    assert len(results) == 1
    assert results[0].provider == "searxng"
    assert results[0].available is False
    assert "searxng crash" in (results[0].error or "")

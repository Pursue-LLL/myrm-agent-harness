"""SSRF tests for wiki URL ingestion."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _fetch_url_as_markdown


@pytest.mark.asyncio
async def test_fetch_url_as_markdown_blocks_ssrf_via_secure_get() -> None:
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
        new_callable=AsyncMock,
        side_effect=SSRFSecurityError("private IP"),
    ):
        with pytest.raises(SSRFSecurityError, match="private IP"):
            await _fetch_url_as_markdown("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_fetch_url_as_markdown_uses_secure_get() -> None:
    mock_response = type(
        "MockResponse",
        (),
        {"status_code": 200, "text": "<html><body><p>ok</p></body></html>"},
    )()

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_secure_get:
        result = await _fetch_url_as_markdown("https://example.com/article")

    mock_secure_get.assert_awaited_once()
    assert mock_secure_get.await_args.kwargs["timeout"] == 30.0
    assert "User-Agent" in mock_secure_get.await_args.kwargs["headers"]
    assert "ok" in result

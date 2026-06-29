"""SSRF tests for A2ACardResolver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.a2a.resolver import A2ACardResolver, SSRFBlockedError


@pytest.mark.asyncio
async def test_resolve_blocks_ssrf_via_secure_get() -> None:
    resolver = A2ACardResolver(cache_ttl_seconds=0)

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
        new_callable=AsyncMock,
        side_effect=SSRFSecurityError("private IP"),
    ):
        with pytest.raises(SSRFBlockedError, match="private IP"):
            await resolver.resolve("https://agent.example.com")


@pytest.mark.asyncio
async def test_resolve_fetches_agent_card_via_secure_get() -> None:
    resolver = A2ACardResolver(cache_ttl_seconds=0)
    card_payload = {
        "name": "Remote Agent",
        "description": "Test agent",
        "skills": [],
    }
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = card_payload

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
        new_callable=AsyncMock,
        return_value=response,
    ) as mock_secure_get:
        card = await resolver.resolve("https://agent.example.com")

    assert card.name == "Remote Agent"
    mock_secure_get.assert_awaited_once()
    call_url = mock_secure_get.await_args.args[0]
    assert call_url.endswith("/.well-known/agent-card.json")


@pytest.mark.asyncio
async def test_skip_ssrf_check_uses_raw_httpx() -> None:
    resolver = A2ACardResolver(cache_ttl_seconds=0)
    card_payload = {"name": "Internal", "description": "trusted", "skills": []}
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = card_payload

    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new_callable=AsyncMock,
        ) as mock_secure_get,
        patch("myrm_agent_harness.toolkits.a2a.resolver.httpx.AsyncClient", return_value=client),
    ):
        card = await resolver.resolve(
            "http://127.0.0.1:8080",
            skip_ssrf_check=True,
        )

    assert card.name == "Internal"
    mock_secure_get.assert_not_called()
    client.get.assert_awaited_once()

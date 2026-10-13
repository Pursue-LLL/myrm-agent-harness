"""Shared fixtures for browser session tests that drive a real Chromium."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.browser import domain_filter
from myrm_agent_harness.toolkits.browser.navigation import ssrf_guard


@pytest.fixture
def loopback_servers_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let a real session reach loopback servers, which the SSRF layers block by design."""
    original = domain_filter._install_http_filter

    async def allow_private(context, allowlist, resource_block, ad_blocklist, domain_blocklist, **_kwargs):
        return await original(
            context, allowlist, resource_block, ad_blocklist, domain_blocklist, allow_private_networks=True
        )

    monkeypatch.setattr(domain_filter, "_install_http_filter", allow_private)
    monkeypatch.setattr(ssrf_guard, "assert_browser_navigation_allowed", AsyncMock(return_value=None))

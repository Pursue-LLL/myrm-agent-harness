"""Live integration tests for SSRF-protected HTTP (no mocks on validation path)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.core.security.http.secure_fetch import secure_get


@pytest.mark.asyncio
async def test_secure_get_blocks_literal_loopback() -> None:
    with pytest.raises(SSRFSecurityError):
        await secure_get("http://127.0.0.1/", timeout=5.0)


@pytest.mark.asyncio
async def test_secure_get_blocks_cloud_metadata_ip() -> None:
    with pytest.raises(SSRFSecurityError):
        await secure_get("http://169.254.169.254/latest/meta-data/", timeout=5.0)


@pytest.mark.asyncio
async def test_robots_parser_live_blocks_metadata_robots() -> None:
    from myrm_agent_harness.toolkits.web_fetch.robots_parser import RobotsParser

    parser = RobotsParser()
    rules = await parser._fetch_robots("http://169.254.169.254/robots.txt")
    assert rules.disallowed == []
    assert rules.sitemaps == []

"""Real OSV.dev network regression for the MCP malware advisory check.

The unit tests stub the HTTP client. These tests query the live OSV API, so they are
``integration`` tests (excluded from the default offline suite). ``check_osv_malware``
is fail-open, so a benign verdict alone proves nothing offline: every test first
requires the known-malicious control to be flagged, which proves OSV was reachable.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from myrm_agent_harness.toolkits.mcp import security
from myrm_agent_harness.toolkits.mcp.security import check_osv_malware, clear_osv_malware_cache

pytestmark = pytest.mark.integration

# ``flatmap-stream`` is the malicious dependency from the 2018 event-stream incident, tracked by OSV as a MAL-* advisory.
_MALICIOUS_ARGS = ["-y", "flatmap-stream"]
_BENIGN_ARGS = ["-y", "@modelcontextprotocol/server-everything"]


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    clear_osv_malware_cache()
    yield
    clear_osv_malware_cache()


async def _flagged_malicious_control() -> str:
    advisory = await check_osv_malware("npx", _MALICIOUS_ARGS)
    assert advisory is not None, "OSV unreachable or the flatmap-stream MAL advisory was withdrawn"
    return advisory


@pytest.mark.asyncio
async def test_osv_flags_a_known_malicious_package_but_not_a_benign_one() -> None:
    advisory = await _flagged_malicious_control()
    assert advisory.startswith("MAL-")
    assert "flatmap-stream" in advisory
    assert await check_osv_malware("npx", _BENIGN_ARGS) is None


@pytest.mark.asyncio
async def test_osv_verdict_is_served_from_the_cache_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    first = await check_osv_malware("npx", _MALICIOUS_ARGS, use_cache=True)
    assert first is not None, "OSV unreachable or the flatmap-stream MAL advisory was withdrawn"

    def _network_forbidden(**_: object) -> object:
        raise AssertionError("cached lookup must not touch the network")

    monkeypatch.setattr(security, "create_httpx_client", _network_forbidden)
    assert await check_osv_malware("npx", _MALICIOUS_ARGS, use_cache=True) == first

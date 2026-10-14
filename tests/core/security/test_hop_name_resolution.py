"""Tests for the bounded, briefly cached name lookup behind the local-mode hop policy.

The lookup decides nothing: it reports every address a hostname resolves to and reports nothing when
the user's resolver cannot answer in time, so a broken or proxy-only DNS setup never blocks browsing.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.core.security.redirect_hop_guard import name_resolution
from myrm_agent_harness.core.security.redirect_hop_guard.name_resolution import resolve_addresses

type _AddrInfo = list[tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[object, ...]]]


def _info(*addresses: str) -> _AddrInfo:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0)) for address in addresses]


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    name_resolution._cache.clear()
    yield
    name_resolution._cache.clear()


async def _resolve_with(answer: AsyncMock, hostname: str = "site.example") -> tuple[str, ...]:
    with patch.object(asyncio.get_running_loop(), "getaddrinfo", answer):
        return tuple(str(address) for address in await resolve_addresses(hostname))


@pytest.mark.asyncio
async def test_localhost_really_resolves_to_loopback() -> None:
    addresses = await resolve_addresses("localhost")
    assert addresses
    assert all(address.is_loopback for address in addresses)


@pytest.mark.asyncio
async def test_every_answer_is_reported_in_order() -> None:
    assert await _resolve_with(AsyncMock(return_value=_info("93.184.216.34", "127.0.0.1"))) == (
        "93.184.216.34",
        "127.0.0.1",
    )


@pytest.mark.asyncio
async def test_an_ipv6_scope_id_is_dropped() -> None:
    answer = AsyncMock(return_value=[(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1%en0", 0, 0, 1))])
    assert await _resolve_with(answer) == ("fe80::1",)


@pytest.mark.asyncio
async def test_unparseable_entries_are_skipped() -> None:
    answer = AsyncMock(return_value=[*_info("not-an-ip"), *_info("203.0.113.9")])
    assert await _resolve_with(answer) == ("203.0.113.9",)


@pytest.mark.asyncio
async def test_a_failed_lookup_reports_nothing() -> None:
    answer = AsyncMock(side_effect=socket.gaierror(socket.EAI_NONAME, "no such host"))
    assert await _resolve_with(answer) == ()


@pytest.mark.asyncio
async def test_a_slow_resolver_is_cut_off_and_reports_nothing() -> None:
    async def never_answers(*_args: object, **_kwargs: object) -> _AddrInfo:
        await asyncio.sleep(30)
        return []

    with patch.object(name_resolution, "_LOOKUP_TIMEOUT_S", 0.05):
        assert await _resolve_with(AsyncMock(side_effect=never_answers)) == ()


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed() -> None:
    answer = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await _resolve_with(answer)


@pytest.mark.asyncio
async def test_the_one_navigation_triggers_share_a_single_lookup() -> None:
    answer = AsyncMock(return_value=_info("127.0.0.1"))
    with patch.object(asyncio.get_running_loop(), "getaddrinfo", answer):
        first = await resolve_addresses("site.example")
        second = await resolve_addresses("site.example")
    assert first == second == (ipaddress.ip_address("127.0.0.1"),)
    answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_failed_lookup_is_remembered_too() -> None:
    """A DNS that cannot answer costs one timeout per host per window, not one per check."""
    answer = AsyncMock(side_effect=socket.gaierror(socket.EAI_AGAIN, "temporary failure"))
    with patch.object(asyncio.get_running_loop(), "getaddrinfo", answer):
        assert await resolve_addresses("site.example") == ()
        assert await resolve_addresses("site.example") == ()
    answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_different_hosts_are_looked_up_separately() -> None:
    answer = AsyncMock(side_effect=lambda host, *_a, **_k: _info("127.0.0.1" if host == "a.example" else "203.0.113.9"))
    with patch.object(asyncio.get_running_loop(), "getaddrinfo", answer):
        assert [str(a) for a in await resolve_addresses("a.example")] == ["127.0.0.1"]
        assert [str(a) for a in await resolve_addresses("b.example")] == ["203.0.113.9"]
    assert answer.await_count == 2

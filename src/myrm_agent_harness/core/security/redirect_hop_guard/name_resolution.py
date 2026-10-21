"""Bounded, briefly cached hostname lookup behind the local-mode hop policy.

[INPUT]
- stdlib asyncio, ipaddress, socket
- myrm_agent_harness.utils.lru_cache::LRUCache (POS: TTL-bounded in-memory cache)

[OUTPUT]
- IPAddress: IPv4 or IPv6 address type
- resolve_addresses: every address a hostname currently resolves to; empty when the resolver cannot answer in time

[POS]
Lets ``RedirectHopEvaluator`` judge a hostname by where it points. The lookup decides nothing and
never raises: an unresolvable or slow name reports no addresses, so a broken or proxy-only resolver
cannot stop browsing. Answers, including empty ones, are remembered for a few seconds, which keeps one
navigation's checks to a single lookup and bounds the cost of a resolver that does not answer to one
timeout per host per window.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

from myrm_agent_harness.utils.lru_cache import LRUCache

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_LOOKUP_TIMEOUT_S = 2.0
_CACHE_TTL_S = 15
_CACHE_MAX_HOSTS = 256

_cache: LRUCache[tuple[IPAddress, ...]] = LRUCache(maxsize=_CACHE_MAX_HOSTS, ttl=_CACHE_TTL_S, id="hop_name_resolution")


async def resolve_addresses(hostname: str) -> tuple[IPAddress, ...]:
    """Return every address ``hostname`` resolves to, or ``()`` when the lookup fails or times out."""
    cached = _cache.get(hostname)
    if cached is not None:
        return cached
    addresses = await _lookup(hostname)
    _cache.set(hostname, addresses)
    return addresses


async def _lookup(hostname: str) -> tuple[IPAddress, ...]:
    try:
        async with asyncio.timeout(_LOOKUP_TIMEOUT_S):
            infos = await asyncio.get_running_loop().getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except (OSError, TimeoutError):
        return ()
    addresses: list[IPAddress] = []
    for *_, sockaddr in infos:
        try:
            # A link-local IPv6 answer carries a "%interface" scope that is not part of the address.
            addresses.append(ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0]))
        except ValueError:
            continue
    return tuple(addresses)

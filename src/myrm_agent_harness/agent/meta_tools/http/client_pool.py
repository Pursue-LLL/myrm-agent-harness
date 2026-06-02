"""HTTP Client Pool - Connection Pooling for Performance

[INPUT]

[OUTPUT]
- httpx.AsyncClient (reused connection pool)

[POS]
HTTP client connection pool. Global singleton reusing TCP connections and TLS handshakes.

"""

from __future__ import annotations

import httpx

_CLIENT_POOL: dict[bool, httpx.AsyncClient] = {}


async def get_http_client(verify_ssl: bool) -> httpx.AsyncClient:
    """Get HTTP client from pool (creates if not exists)

    Args:
        verify_ssl: SSL verification flag

    Returns:
        httpx.AsyncClient (reused)
    """
    if verify_ssl not in _CLIENT_POOL:
        _CLIENT_POOL[verify_ssl] = httpx.AsyncClient(
            verify=verify_ssl,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            timeout=httpx.Timeout(30.0),
        )
    return _CLIENT_POOL[verify_ssl]


async def close_http_client() -> None:
    """Close all HTTP clients in pool (on app shutdown)"""
    for client in _CLIENT_POOL.values():
        await client.aclose()
    _CLIENT_POOL.clear()

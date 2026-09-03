"""SSRF-protected HTTP fetch with per-hop DNS pinning and redirect validation.

[INPUT]
- myrm_agent_harness.core.security.guards.ssrf::async_pin_url (POS: DNS-pinned URL validation)
- myrm_agent_harness.core.security.guards.ssrf::SSRFSecurityError (POS: blocked URL errors)

[OUTPUT]
- secure_get / secure_request: SSRF-safe HTTP with manual redirect loop
- resolve_secure_http_target: pinned target for streaming callers
- ContentTooLargeError: raised when a response body exceeds max_content_length
- DEFAULT_MAX_CONTENT_LENGTH: secure-by-default response body cap (20 MB)

[POS]
Shared outbound HTTP primitive for all harness and server paths that must not bypass SSRF guards.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from myrm_agent_harness.core.security.guards.ssrf import (
    SSRFSecurityError,
    async_pin_url,
)
from myrm_agent_harness.core.security.http.redirect_guard import (
    strip_sensitive_headers_on_redirect,
)
from myrm_agent_harness.infra.tls_compat import create_httpx_client

logger = logging.getLogger(__name__)

DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB secure-by-default body cap
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
_METHODS_WITH_BODY = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True, slots=True)
class SecureHttpTarget:
    """Final hop of a redirect chain, ready for streaming or follow-up requests."""

    logical_url: str
    request_url: str
    headers: dict[str, str]
    method: str


class ContentTooLargeError(Exception):
    """Raised when a response body exceeds the configured ``max_content_length``."""


def is_ssrf_shield_enabled() -> bool:
    """Return whether outbound SSRF shield is active (default: enabled)."""
    return os.getenv("MYRM_ENABLE_SSRF_SHIELD", "true").lower() in ("true", "1", "yes")


def parse_allowed_internal_hosts() -> list[str]:
    """Parse MYRM_ALLOWED_INTERNAL_HOSTS env var into a host list."""
    raw = os.getenv("MYRM_ALLOWED_INTERNAL_HOSTS", "")
    return [host.strip() for host in raw.split(",") if host.strip()]


async def _pin_or_passthrough(
    logical_url: str,
    *,
    allowed_internal_hosts: list[str],
    enable_ssrf_shield: bool,
) -> tuple[str, dict[str, str]]:
    if not enable_ssrf_shield:
        return logical_url, {}
    request_url, pin_headers = await async_pin_url(logical_url, allowed_internal_hosts)
    return request_url, pin_headers


def _next_redirect(
    *,
    logical_url: str,
    current_method: str,
    status_code: int,
    location: str | None,
) -> tuple[str, str] | None:
    """Compute the next hop after a redirect response, or None when the chain ends."""
    if status_code not in _REDIRECT_STATUS or not location:
        return None

    next_url = urljoin(logical_url, location)
    next_method = current_method
    if status_code in (301, 302, 303) and current_method in _METHODS_WITH_BODY:
        next_method = "GET"
    return next_url, next_method


def _https_pin_extensions(request_url: str, pin_headers: dict[str, str]) -> dict[str, object]:
    """Return httpx transport extensions for DNS-pinned HTTPS hops.

    DNS pinning connects to a resolved IP while preserving the logical Host header.
    TLS SNI must still use the original hostname or CDNs (e.g. OpenCode Go) reject the
    handshake with SSLV3_ALERT_HANDSHAKE_FAILURE.
    """
    host_header = pin_headers.get("Host", "").strip()
    if not host_header:
        return {}

    parsed = urlparse(request_url)
    if parsed.scheme.lower() != "https":
        return {}

    hop_host = (parsed.hostname or "").strip()
    if not hop_host:
        return {}

    try:
        ipaddress.ip_address(hop_host)
    except ValueError:
        return {}

    return {"sni_hostname": host_header}


async def resolve_secure_http_target(
    client: httpx.AsyncClient,
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    allowed_internal_hosts: list[str] | None = None,
    enable_ssrf_shield: bool | None = None,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> SecureHttpTarget:
    """Follow redirects with SSRF checks and return the pinned final-hop target."""
    shield_enabled = is_ssrf_shield_enabled() if enable_ssrf_shield is None else enable_ssrf_shield
    allowed_hosts = parse_allowed_internal_hosts() if allowed_internal_hosts is None else allowed_internal_hosts

    logical_url = url
    current_method = method.upper()
    request_headers = dict(headers or {})
    redirect_count = 0

    while redirect_count <= max_redirects:
        try:
            request_url, pin_headers = await _pin_or_passthrough(
                logical_url,
                allowed_internal_hosts=allowed_hosts,
                enable_ssrf_shield=shield_enabled,
            )
        except SSRFSecurityError as exc:
            logger.error("SSRF blocked during redirect resolution: %s", exc)
            raise

        hop_headers = {**request_headers, **pin_headers}
        pin_extensions = _https_pin_extensions(request_url, pin_headers)
        response = await client.send(
            client.build_request(
                current_method,
                request_url,
                headers=hop_headers,
                params=params if redirect_count == 0 else None,
                extensions=pin_extensions,
            ),
            stream=True,
        )

        try:
            redirected = _next_redirect(
                logical_url=logical_url,
                current_method=current_method,
                status_code=response.status_code,
                location=response.headers.get("Location") or response.headers.get("location"),
            )
            if redirected is None:
                return SecureHttpTarget(
                    logical_url=logical_url,
                    request_url=request_url,
                    headers=hop_headers,
                    method=current_method,
                )

            logical_url, current_method = redirected
            request_headers = strip_sensitive_headers_on_redirect(
                from_url=url if redirect_count == 0 else logical_url,
                to_url=logical_url,
                headers=request_headers,
                tool_name="secure_http_target_resolution",
            )
            redirect_count += 1
            if redirect_count > max_redirects:
                raise SSRFSecurityError(f"Too many redirects (limit: {max_redirects}) for {url}")
        finally:
            await response.aclose()

    raise SSRFSecurityError(f"Too many redirects (limit: {max_redirects}) for {url}")


async def secure_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    json: object | None = None,
    content: bytes | str | None = None,
    timeout: float | httpx.Timeout | None = None,
    allowed_internal_hosts: list[str] | None = None,
    enable_ssrf_shield: bool | None = None,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_content_length: int | None = DEFAULT_MAX_CONTENT_LENGTH,
) -> httpx.Response:
    """Execute an HTTP request with SSRF shield and manual redirect handling.

    The response body is streamed and aborted as soon as it exceeds
    ``max_content_length`` (secure-by-default cap of 20 MB), so oversized
    responses never fully load into memory. Pass ``None`` to disable the cap.
    """
    shield_enabled = is_ssrf_shield_enabled() if enable_ssrf_shield is None else enable_ssrf_shield
    allowed_hosts = parse_allowed_internal_hosts() if allowed_internal_hosts is None else allowed_internal_hosts

    logical_url = url
    current_method = method.upper()
    request_headers = dict(headers or {})
    redirect_count = 0
    response: httpx.Response | None = None

    while redirect_count <= max_redirects:
        try:
            request_url, pin_headers = await _pin_or_passthrough(
                logical_url,
                allowed_internal_hosts=allowed_hosts,
                enable_ssrf_shield=shield_enabled,
            )
        except SSRFSecurityError as exc:
            logger.error("SSRF blocked: %s", exc)
            raise

        hop_headers = {**request_headers, **pin_headers}
        pin_extensions = _https_pin_extensions(request_url, pin_headers)
        request = client.build_request(
            current_method,
            request_url,
            headers=hop_headers,
            params=params if redirect_count == 0 else None,
            json=json if redirect_count == 0 else None,
            content=content if redirect_count == 0 else None,
            extensions=pin_extensions,
            timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
        )
        response = await client.send(request, stream=True)

        redirected = _next_redirect(
            logical_url=logical_url,
            current_method=current_method,
            status_code=response.status_code,
            location=response.headers.get("Location") or response.headers.get("location"),
        )
        if redirected is None:
            break

        await response.aclose()
        prev_url = logical_url
        response = None
        logical_url, current_method = redirected
        request_headers = strip_sensitive_headers_on_redirect(
            from_url=prev_url,
            to_url=logical_url,
            headers=request_headers,
            tool_name="secure_http_request",
        )
        redirect_count += 1
        if redirect_count > max_redirects:
            raise SSRFSecurityError(f"Too many redirects (limit: {max_redirects}) for {url}")

    if response is None:
        raise ValueError(f"No response received for {url}")

    if max_content_length is None:
        await response.aread()
    else:
        declared_length = response.headers.get("Content-Length")
        if declared_length is not None and declared_length.isdigit() and int(declared_length) > max_content_length:
            await response.aclose()
            raise ContentTooLargeError(f"Response body exceeds {max_content_length} byte limit")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_content_length:
                await response.aclose()
                raise ContentTooLargeError(f"Response body exceeds {max_content_length} byte limit")
            chunks.append(chunk)
        # httpx leaves `_content` unset on streamed responses; backfill it so
        # callers can read `.content`/`.json()` after the size-capped read.
        response._content = b"".join(chunks)
        await response.aclose()

    return response


async def secure_get(
    url: str,
    *,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    allowed_internal_hosts: list[str] | None = None,
    enable_ssrf_shield: bool | None = None,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_content_length: int | None = DEFAULT_MAX_CONTENT_LENGTH,
) -> httpx.Response:
    """Perform a GET request with SSRF shield and manual redirect handling."""
    async with create_httpx_client(timeout=timeout, follow_redirects=False) as client:
        return await secure_request(
            client,
            "GET",
            url,
            headers=headers,
            timeout=timeout,
            allowed_internal_hosts=allowed_internal_hosts,
            enable_ssrf_shield=enable_ssrf_shield,
            max_redirects=max_redirects,
            max_content_length=max_content_length,
        )


__all__ = [
    "DEFAULT_MAX_CONTENT_LENGTH",
    "DEFAULT_MAX_REDIRECTS",
    "ContentTooLargeError",
    "SecureHttpTarget",
    "is_ssrf_shield_enabled",
    "parse_allowed_internal_hosts",
    "resolve_secure_http_target",
    "secure_get",
    "secure_request",
]

"""L1 HTTP fetcher via Scrapling curl_cffi with optional HTTP/3 retry lane.

[INPUT]
- core.security.guards.ssrf::SSRFSecurityError (POS: SSRF shield for outbound HTTP)
- toolkits.web_fetch.antibot_detector::is_blocked (POS: Anti-bot detection for crawl results)
- toolkits.web_fetch.http3_probe::is_quic_egress_available (POS: QUIC egress probe and L1 retry metrics)
- toolkits.web_fetch.router.site_experience::get_global_site_experience_store (POS: Site experience store)
- toolkits.browser.pool.proxy::ProxyPool (POS: Proxy rotation pool for FetchEngine)

[OUTPUT]
- HttpFetcher: L1 tier fetcher with HTTP/2 default and HTTP/3 retry on antibot/403/empty failure (not 429; skipped when proxy pool active)

[POS]
L1 lightweight HTTP fetcher. Delegates TLS impersonation to Scrapling defaults; retries once with QUIC when enabled.
"""

from __future__ import annotations

import asyncio
import http.cookiejar
import logging
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from myrm_agent_harness.core.security.guards.ssrf import (
    SSRFSecurityError,
    async_pin_url,
)
from myrm_agent_harness.core.security.http.secure_fetch import (
    is_ssrf_shield_enabled,
    parse_allowed_internal_hosts,
)
from myrm_agent_harness.toolkits.web_fetch.antibot_detector import (
    is_blocked as detect_antibot,
)
from myrm_agent_harness.toolkits.web_fetch.http3_probe import (
    is_quic_egress_available,
    record_http3_retry,
)
from myrm_agent_harness.toolkits.web_fetch.router.site_experience import (
    get_global_site_experience_store,
)

from .protocols import FetcherType, FetchResult

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyPool
    from myrm_agent_harness.toolkits.browser.session_vault import SessionVault

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10
_MAX_CONCURRENT = 20
_MAX_REDIRECTS = 5
_HTTP3_RETRY_STATUS = frozenset({403})


DEFAULT_MAX_RESPONSE_BYTES = 750_000


class HttpFetcher:
    """L1 tier: curl_cffi HTTP requests, TLS fingerprint spoofing"""

    fetcher_type = FetcherType.HTTP

    def __init__(
        self,
        max_concurrent: int = _MAX_CONCURRENT,
        timeout: int = _DEFAULT_TIMEOUT,
        proxy_pool: ProxyPool | None = None,
        session_vault: SessionVault | None = None,
    ):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._timeout = timeout
        self._proxy_pool = proxy_pool
        self._session_vault = session_vault

    async def fetch(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult | None:
        enable_ssrf_shield = is_ssrf_shield_enabled()
        allowed_hosts = parse_allowed_internal_hosts()

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        cookie_jar = await self._load_cookie_jar(url)
        domain = self._extract_domain(url)
        site_store = get_global_site_experience_store()
        prefer_http3 = site_store.get_prefer_http3(domain)
        can_use_http3 = await self._can_use_http3_lane()

        async with self._semaphore:
            if prefer_http3 and can_use_http3:
                prefer_result = await self._fetch_with_redirects(
                    url,
                    headers=headers,
                    cookie_jar=cookie_jar,
                    enable_ssrf_shield=enable_ssrf_shield,
                    allowed_hosts=allowed_hosts,
                    use_http3=True,
                )
                if prefer_result is not None and not self._should_retry_with_http3(
                    prefer_result
                ):
                    return prefer_result

                site_store.set_prefer_http3(domain, enabled=False)
                logger.info(
                    "L1 HTTP/3 prefer_http3 cleared for %s after QUIC failure", domain
                )
                return prefer_result

            http2_result = await self._fetch_with_redirects(
                url,
                headers=headers,
                cookie_jar=cookie_jar,
                enable_ssrf_shield=enable_ssrf_shield,
                allowed_hosts=allowed_hosts,
                use_http3=False,
            )

            if not self._should_retry_with_http3(http2_result):
                return http2_result

            if not can_use_http3:
                return http2_result

            logger.info("L1 HTTP/2 blocked for %s; retrying once with HTTP/3", url)
            http3_result = await self._fetch_with_redirects(
                url,
                headers=headers,
                cookie_jar=cookie_jar,
                enable_ssrf_shield=enable_ssrf_shield,
                allowed_hosts=allowed_hosts,
                use_http3=True,
            )

            http3_succeeded = (
                http3_result is not None
                and not self._should_retry_with_http3(http3_result)
            )
            record_http3_retry(succeeded=http3_succeeded)
            if http3_succeeded:
                site_store.set_prefer_http3(domain)
                return http3_result

            return http2_result if http2_result is not None else http3_result

    async def _can_use_http3_lane(self) -> bool:
        if self._proxy_pool is not None:
            return False
        return await is_quic_egress_available()

    @staticmethod
    def _extract_domain(url: str) -> str:
        hostname = (urlparse(url).hostname or "").lower()
        if hostname.startswith("www."):
            return hostname[4:]
        return hostname

    async def _load_cookie_jar(self, url: str) -> http.cookiejar.CookieJar | None:
        if not self._session_vault:
            return None

        try:
            domain = self._extract_domain(url)
            entry = await self._session_vault.load(domain)
            if (
                not entry
                or not entry.storage_state
                or "cookies" not in entry.storage_state
            ):
                return None

            cookie_jar = http.cookiejar.CookieJar()
            for cookie in entry.storage_state["cookies"]:
                c_domain = cookie.get("domain", "")
                c_path = cookie.get("path", "/")
                c_secure = cookie.get("secure", False)
                c_expires = cookie.get("expires")
                if c_expires in (-1, 0, None):
                    c_expires = None

                cookie_jar.set_cookie(
                    http.cookiejar.Cookie(
                        version=0,
                        name=cookie["name"],
                        value=cookie["value"],
                        port=None,
                        port_specified=False,
                        domain=c_domain,
                        domain_specified=bool(c_domain),
                        domain_initial_dot=c_domain.startswith("."),
                        path=c_path,
                        path_specified=bool(c_path),
                        secure=c_secure,
                        expires=c_expires,
                        discard=False,
                        comment=None,
                        comment_url=None,
                        rest={"HttpOnly": cookie.get("httpOnly", False)},
                        rfc2109=False,
                    )
                )
            return cookie_jar
        except Exception as exc:
            logger.warning(
                "HttpFetcher failed to load session cookies for %s: %s", url, exc
            )
            return None

    @staticmethod
    def _should_retry_with_http3(result: FetchResult | None) -> bool:
        if result is None:
            return True

        if result.status_code == 304:
            return False

        if result.status_code == 429:
            return False

        if result.status_code in _HTTP3_RETRY_STATUS:
            return True

        if 400 <= result.status_code < 500:
            return False

        if result.raw_body is not None:
            return False

        if not result.has_content:
            return True

        blocked, _reason = detect_antibot(result.status_code, result.html)
        return blocked

    async def _fetch_with_redirects(
        self,
        url: str,
        *,
        headers: dict[str, str],
        cookie_jar: http.cookiejar.CookieJar | None,
        enable_ssrf_shield: bool,
        allowed_hosts: list[str],
        use_http3: bool,
    ) -> FetchResult | None:
        from scrapling.fetchers import AsyncFetcher  # type: ignore[import-untyped]

        current_url = url
        redirect_count = 0
        request_headers = headers.copy()

        while redirect_count <= _MAX_REDIRECTS:
            request_url = current_url

            if enable_ssrf_shield:
                try:
                    safe_url, host_header = await async_pin_url(
                        current_url, allowed_hosts
                    )
                    request_url = safe_url
                    request_headers.update(host_header)
                except SSRFSecurityError as exc:
                    logger.error("SSRF attempt blocked in HttpFetcher: %s", exc)
                    return None

            try:
                kwargs = self._build_request_kwargs(
                    request_headers,
                    cookie_jar,
                    use_http3=use_http3,
                )
                response = await AsyncFetcher.get(request_url, **kwargs)

                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location") or response.headers.get(
                        "location"
                    )
                    if not location:
                        break
                    current_url = urljoin(current_url, location)
                    redirect_count += 1
                    continue

                return self._response_to_fetch_result(response, current_url)
            except Exception as exc:
                logger.warning("HttpFetcher failed at %s — %s", current_url, exc)
                return None

        logger.warning(
            "HttpFetcher failed: Too many redirects (%s) for %s", _MAX_REDIRECTS, url
        )
        return None

    def _build_request_kwargs(
        self,
        headers: dict[str, str],
        cookie_jar: http.cookiejar.CookieJar | None,
        *,
        use_http3: bool,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "timeout": self._timeout,
            "follow_redirects": False,
            "retries": 1,
        }

        if headers:
            kwargs["headers"] = headers.copy()

        if use_http3:
            kwargs["http3"] = True
            kwargs["impersonate"] = None

        if self._proxy_pool:
            kwargs["proxy"] = self._proxy_pool.get_next().to_url()

        if cookie_jar is not None:
            kwargs["cookies"] = cookie_jar

        return kwargs

    @staticmethod
    def _response_to_fetch_result(response: object, current_url: str) -> FetchResult:
        status = getattr(response, "status", 200)
        resp_headers = dict(getattr(response, "headers", {}) or {})
        response_url = getattr(response, "url", None) or current_url

        if status == 304:
            return FetchResult(
                html="",
                url=response_url,
                status_code=304,
                headers=resp_headers,
                fetcher_type=FetcherType.HTTP,
            )

        content_type = (
            (resp_headers.get("content-type") or "").split(";")[0].strip().lower()
        )
        is_text = (
            not content_type
            or content_type.startswith("text/")
            or content_type
            in ("application/json", "application/xml", "application/javascript")
        )

        body = getattr(response, "body", b"")
        if len(body) > DEFAULT_MAX_RESPONSE_BYTES:
            logger.warning(
                "L1 HTTP response body capped: %d -> %d bytes for %s",
                len(body),
                DEFAULT_MAX_RESPONSE_BYTES,
                current_url,
            )
            body = body[:DEFAULT_MAX_RESPONSE_BYTES]
        encoding = getattr(response, "encoding", None) or "utf-8"

        if is_text:
            html = body.decode(encoding, errors="replace")
            return FetchResult(
                html=html,
                url=response_url,
                status_code=status,
                headers=resp_headers,
                fetcher_type=FetcherType.HTTP,
            )

        return FetchResult(
            html="",
            url=response_url,
            status_code=status,
            headers=resp_headers,
            fetcher_type=FetcherType.HTTP,
            raw_body=body,
        )

    async def shutdown(self) -> None:
        pass

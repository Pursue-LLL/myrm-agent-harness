"""Live integration tests for SSRF protection on the real DNS path.

Key-path validation is unmocked: real DNS resolution, real private-IP range
checks, real FetchEngine crawl entry guards. No scrapling-dependent fetch is
performed, so the suite is safe with or without the ``[web]`` extra.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from myrm_agent_harness.core.security.guards.ssrf import (
    SSRFSecurityError,
    async_pin_url,
    async_validate_url_for_ssrf,
    check_url,
    clear_dynamic_blocked_hostnames,
    register_blocked_hostnames,
    resolve_and_check,
    validate_url_for_ssrf,
)
from myrm_agent_harness.toolkits.browser.domain_filter import DomainAllowlist
from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine


class TestSyncValidateRealDns:
    def test_public_url_resolves_and_is_safe(self) -> None:
        result = validate_url_for_ssrf("https://example.com/path?q=1")
        assert result.safe is True
        assert result.resolved_ips, "public hostname must resolve to real IPs"

    def test_private_ip_literals_blocked(self) -> None:
        for url in (
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://192.168.1.1/x",
            "http://169.254.169.254/latest/meta-data/",
        ):
            result = validate_url_for_ssrf(url)
            assert result.safe is False, f"{url} must be blocked"

    def test_invalid_scheme_blocked(self) -> None:
        assert validate_url_for_ssrf("ftp://example.com/file").safe is False
        assert validate_url_for_ssrf("file:///etc/passwd").safe is False


class TestAsyncValidateRealDns:
    @pytest.mark.asyncio
    async def test_async_public_url_safe(self) -> None:
        result = await async_validate_url_for_ssrf("https://example.com/")
        assert result.safe is True
        assert result.resolved_ips

    @pytest.mark.asyncio
    async def test_async_private_ip_blocked(self) -> None:
        result = await async_validate_url_for_ssrf("http://169.254.169.254/")
        assert result.safe is False

    @pytest.mark.asyncio
    async def test_pin_url_returns_pinned_ip_and_host(self) -> None:
        safe_url, headers = await async_pin_url("https://example.com/path")
        assert headers["Host"] == "example.com"
        assert "example.com" not in safe_url
        assert safe_url.startswith("https://")

    @pytest.mark.asyncio
    async def test_pin_url_blocks_private(self) -> None:
        with pytest.raises(SSRFSecurityError):
            await async_pin_url("http://169.254.169.254/latest/meta-data/")


class TestResolveAndCheckRealDns:
    def test_localhost_resolution_blocked(self) -> None:
        verdict = resolve_and_check("localhost")
        assert verdict.allowed is False
        assert "private/internal" in verdict.reason or "127.0.0.1" in verdict.reason

    def test_check_url_private_ip_fast_path(self) -> None:
        assert check_url("http://127.0.0.1/").allowed is False
        assert check_url("https://example.com/").allowed is True


class TestFetchEngineCrawlRealGuards:
    def _make_engine(self, tmpdir: str, **kwargs) -> FetchEngine:
        kwargs.setdefault("adaptive_router_rules_file", Path(tmpdir) / "rules.pkl")
        return FetchEngine(**kwargs)

    @pytest.mark.asyncio
    async def test_crawl_blocks_private_ip_before_any_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._make_engine(tmp)
            try:
                doc = await engine.crawl("http://127.0.0.1/admin")
                assert doc is None
            finally:
                await engine.shutdown()

    @pytest.mark.asyncio
    async def test_crawl_honors_domain_allowlist(self) -> None:
        allowlist = DomainAllowlist.from_strings(["allowed.example"])
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._make_engine(tmp, domain_allowlist=allowlist)
            engine._allow_private_networks = True  # 隔离白名单层，跳过 IP 校验
            try:
                doc = await engine.crawl("http://blocked.example/page")
                assert doc is None
            finally:
                await engine.shutdown()

    def test_dynamic_hostnames_live_dns_block(self) -> None:
        clear_dynamic_blocked_hostnames()
        try:
            # example.com is a public valid URL
            assert validate_url_for_ssrf("https://example.com/api").safe is True

            register_blocked_hostnames("example.com")
            blocked = validate_url_for_ssrf("https://example.com/api")
            assert blocked.safe is False
            assert "Blocked hostname: example.com" in blocked.error
        finally:
            clear_dynamic_blocked_hostnames()


"""Unit tests for RobotsParser SSRF-safe fetch and rule parsing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.web_fetch.robots_parser import RobotsParser, RobotsRules


class TestRobotsRules:
    def test_disallow_blocks_path(self) -> None:
        rules = RobotsRules(disallowed=["/private"], allowed=[], crawl_delay=None, sitemaps=[])
        assert rules.is_path_allowed("/public") is True
        assert rules.is_path_allowed("/private/secret") is False

    def test_allow_overrides_disallow(self) -> None:
        rules = RobotsRules(
            disallowed=["/docs"],
            allowed=["/docs/public"],
            crawl_delay=None,
            sitemaps=[],
        )
        assert rules.is_path_allowed("/docs/public/page") is True
        assert rules.is_path_allowed("/docs/internal") is False

    def test_wildcard_pattern(self) -> None:
        rules = RobotsRules(disallowed=["/tmp/*"], allowed=[], crawl_delay=None, sitemaps=[])
        assert rules.is_path_allowed("/tmp/file") is False
        assert rules.is_path_allowed("/other") is True

    def test_empty_disallow_pattern(self) -> None:
        rules = RobotsRules(disallowed=[""], allowed=[], crawl_delay=None, sitemaps=[])
        assert rules.is_path_allowed("/any") is True

    def test_root_disallow(self) -> None:
        rules = RobotsRules(disallowed=["/"], allowed=[], crawl_delay=None, sitemaps=[])
        assert rules.is_path_allowed("/anything") is False


class TestRobotsParser:
    @pytest.mark.asyncio
    async def test_fetch_and_parse_success(self) -> None:
        body = (
            "User-agent: *\n"
            "Disallow: /admin\n"
            "Crawl-delay: 2\n"
            "Sitemap: https://example.com/sitemap.xml\n"
        )
        response = httpx.Response(200, text=body, request=httpx.Request("GET", "https://example.com/robots.txt"))
        parser = RobotsParser()

        with patch(
            "myrm_agent_harness.toolkits.web_fetch.robots_parser.secure_get",
            new=AsyncMock(return_value=response),
        ):
            rules = await parser.fetch_and_parse("https://example.com/page")

        assert rules.disallowed == ["/admin"]
        assert rules.crawl_delay == 2.0
        assert rules.sitemaps == ["https://example.com/sitemap.xml"]

    @pytest.mark.asyncio
    async def test_fetch_and_parse_uses_cache(self) -> None:
        parser = RobotsParser()
        cached = RobotsRules(["/x"], [], None, [])
        parser._cache["https://example.com"] = cached

        with patch(
            "myrm_agent_harness.toolkits.web_fetch.robots_parser.secure_get",
            new=AsyncMock(),
        ) as mock_get:
            rules = await parser.fetch_and_parse("https://example.com/page")

        assert rules is cached
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_robots_non_200_returns_permissive(self) -> None:
        response = httpx.Response(404, text="", request=httpx.Request("GET", "https://example.com/robots.txt"))
        parser = RobotsParser()

        with patch(
            "myrm_agent_harness.toolkits.web_fetch.robots_parser.secure_get",
            new=AsyncMock(return_value=response),
        ):
            rules = await parser._fetch_robots("https://example.com/robots.txt")

        assert rules.disallowed == []
        assert rules.sitemaps == []

    @pytest.mark.asyncio
    async def test_fetch_robots_ssrf_block_returns_permissive(self) -> None:
        parser = RobotsParser()
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.robots_parser.secure_get",
            new=AsyncMock(side_effect=SSRFSecurityError("Blocked")),
        ):
            rules = await parser._fetch_robots("http://169.254.169.254/robots.txt")

        assert rules.sitemaps == []

    def test_parse_content_ignores_unrelated_user_agent(self) -> None:
        parser = RobotsParser(user_agent="MyBot")
        content = (
            "User-agent: OtherBot\n"
            "Disallow: /nope\n"
            "User-agent: MyBot\n"
            "Disallow: /yes\n"
            "Allow: /yes/public\n"
        )
        rules = parser._parse_content(content)
        assert rules.disallowed == ["/yes"]
        assert rules.allowed == ["/yes/public"]

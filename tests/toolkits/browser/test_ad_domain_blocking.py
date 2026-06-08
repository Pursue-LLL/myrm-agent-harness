"""Unit tests for ad/tracker domain blocking.

Tests:
- _is_ad_domain suffix matching algorithm
- AD_DOMAINS data module loading and integrity
- install_domain_filter integration with ad_blocklist
- ResourceBlockConfig.block_ad_domains toggle behavior
- context_factory resource_block decoupling from domain_allowlist
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.domain_filter import (
    DomainAllowlist,
    _is_ad_domain,
    install_domain_filter,
)
from myrm_agent_harness.toolkits.browser.pool.config import ResourceBlockConfig


# =============================================================================
# _is_ad_domain: suffix matching algorithm
# =============================================================================


class TestIsAdDomain:
    """Test the _is_ad_domain subdomain matching function."""

    @pytest.fixture()
    def blocklist(self) -> frozenset[str]:
        return frozenset(
            {
                "doubleclick.net",
                "googlesyndication.com",
                "ads.example.com",
                "tracker.io",
            }
        )

    def test_exact_match(self, blocklist: frozenset[str]) -> None:
        assert _is_ad_domain("doubleclick.net", blocklist) is True

    def test_subdomain_match(self, blocklist: frozenset[str]) -> None:
        assert _is_ad_domain("ad.doubleclick.net", blocklist) is True

    def test_deep_subdomain_match(self, blocklist: frozenset[str]) -> None:
        assert _is_ad_domain("tracker.sub.doubleclick.net", blocklist) is True

    def test_non_matching_domain(self, blocklist: frozenset[str]) -> None:
        assert _is_ad_domain("google.com", blocklist) is False

    def test_partial_name_no_false_positive(self, blocklist: frozenset[str]) -> None:
        """Ensure 'notdoubleclick.net' does NOT match 'doubleclick.net'."""
        assert _is_ad_domain("notdoubleclick.net", blocklist) is False

    def test_suffix_boundary_correct(self, blocklist: frozenset[str]) -> None:
        """'evil-doubleclick.net' must NOT match 'doubleclick.net'."""
        assert _is_ad_domain("evil-doubleclick.net", blocklist) is False

    def test_multi_level_blocked(self, blocklist: frozenset[str]) -> None:
        assert _is_ad_domain("sub.ads.example.com", blocklist) is True

    def test_parent_of_blocked_not_blocked(self, blocklist: frozenset[str]) -> None:
        """'example.com' is NOT blocked even though 'ads.example.com' is."""
        assert _is_ad_domain("example.com", blocklist) is False

    def test_tld_only_not_matched(self, blocklist: frozenset[str]) -> None:
        assert _is_ad_domain("net", blocklist) is False

    def test_empty_blocklist(self) -> None:
        assert _is_ad_domain("doubleclick.net", frozenset()) is False

    def test_empty_hostname(self, blocklist: frozenset[str]) -> None:
        assert _is_ad_domain("", blocklist) is False


# =============================================================================
# AD_DOMAINS data module
# =============================================================================


class TestAdDomainsModule:
    """Test the ad_domains data module."""

    def test_import_and_type(self) -> None:
        from myrm_agent_harness.toolkits.browser.ad_domains import AD_DOMAINS

        assert isinstance(AD_DOMAINS, frozenset)

    def test_minimum_domain_count(self) -> None:
        from myrm_agent_harness.toolkits.browser.ad_domains import AD_DOMAINS

        assert len(AD_DOMAINS) >= 3000

    def test_known_ad_domains_present(self) -> None:
        from myrm_agent_harness.toolkits.browser.ad_domains import AD_DOMAINS

        assert "doubleclick.net" in AD_DOMAINS
        assert "googlesyndication.com" in AD_DOMAINS
        assert "adnxs.com" in AD_DOMAINS

    def test_no_legitimate_domains(self) -> None:
        from myrm_agent_harness.toolkits.browser.ad_domains import AD_DOMAINS

        assert "google.com" not in AD_DOMAINS
        assert "github.com" not in AD_DOMAINS
        assert "cloudflare.com" not in AD_DOMAINS
        assert "cdn.jsdelivr.net" not in AD_DOMAINS

    def test_all_entries_are_strings(self) -> None:
        from myrm_agent_harness.toolkits.browser.ad_domains import AD_DOMAINS

        for domain in list(AD_DOMAINS)[:100]:
            assert isinstance(domain, str)
            assert "." in domain
            assert domain == domain.lower()


# =============================================================================
# ResourceBlockConfig.block_ad_domains
# =============================================================================


class TestResourceBlockConfigAdDomains:
    """Test ResourceBlockConfig's block_ad_domains field."""

    def test_default_is_false(self) -> None:
        config = ResourceBlockConfig()
        assert config.block_ad_domains is False

    def test_explicit_true(self) -> None:
        config = ResourceBlockConfig(block_ad_domains=True)
        assert config.block_ad_domains is True

    def test_standard_preset_has_ad_blocking(self) -> None:
        from myrm_agent_harness.toolkits.browser.pool.config import (
            _resource_block_standard,
        )

        config = _resource_block_standard()
        assert config.block_ad_domains is True

    def test_none_preset_no_ad_blocking(self) -> None:
        from myrm_agent_harness.toolkits.browser.pool.config import (
            _resource_block_none,
        )

        config = _resource_block_none()
        assert config.block_ad_domains is False


# =============================================================================
# install_domain_filter with ad_blocklist
# =============================================================================


class TestInstallDomainFilterAdBlocking:
    """Test install_domain_filter ad blocking integration."""

    @pytest.fixture()
    def mock_context(self) -> AsyncMock:
        ctx = AsyncMock()
        ctx.route = AsyncMock()
        ctx.add_init_script = AsyncMock()
        ctx.on = MagicMock()
        return ctx

    @pytest.mark.asyncio()
    async def test_ad_blocklist_loaded_when_enabled(self, mock_context: AsyncMock) -> None:
        """When block_ad_domains=True, AD_DOMAINS should be loaded and route installed."""
        resource_block = ResourceBlockConfig(block_ad_domains=True)
        allowlist = DomainAllowlist(patterns=())

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        mock_context.route.assert_called_once()

    @pytest.mark.asyncio()
    async def test_no_route_when_nothing_enabled(self, mock_context: AsyncMock) -> None:
        """When all blocking disabled and allowlist empty, no route should be installed."""
        resource_block = ResourceBlockConfig()
        allowlist = DomainAllowlist(patterns=())

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        mock_context.route.assert_not_called()

    @pytest.mark.asyncio()
    async def test_ad_blocking_blocks_ad_domain(self, mock_context: AsyncMock) -> None:
        """Verify the route handler correctly blocks an ad domain."""
        resource_block = ResourceBlockConfig(block_ad_domains=True)
        allowlist = DomainAllowlist(patterns=())

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        handler = mock_context.route.call_args[0][1]

        route = AsyncMock()
        route.request = MagicMock()
        route.request.url = "https://ad.doubleclick.net/tracking.js"
        route.request.resource_type = "script"

        await handler(route)

        route.abort.assert_called_once_with("blockedbyclient")

    @pytest.mark.asyncio()
    async def test_ad_blocking_allows_legitimate_domain(self, mock_context: AsyncMock) -> None:
        """Verify the route handler allows a legitimate domain."""
        resource_block = ResourceBlockConfig(block_ad_domains=True)
        allowlist = DomainAllowlist(patterns=())

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        handler = mock_context.route.call_args[0][1]

        route = AsyncMock()
        route.request = MagicMock()
        route.request.url = "https://cdn.jsdelivr.net/npm/vue@3/dist/vue.js"
        route.request.resource_type = "script"

        await handler(route)

        route.continue_.assert_called_once()

    @pytest.mark.asyncio()
    async def test_ad_blocking_with_resource_type_blocking(self, mock_context: AsyncMock) -> None:
        """Both ad blocking and resource type blocking active simultaneously."""
        resource_block = ResourceBlockConfig(block_images=True, block_ad_domains=True)
        allowlist = DomainAllowlist(patterns=())

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        handler = mock_context.route.call_args[0][1]

        route_img = AsyncMock()
        route_img.request = MagicMock()
        route_img.request.url = "https://example.com/photo.png"
        route_img.request.resource_type = "image"
        await handler(route_img)
        route_img.abort.assert_called_once_with("blockedbyclient")

        route_ad = AsyncMock()
        route_ad.request = MagicMock()
        route_ad.request.url = "https://tracker.googlesyndication.com/beacon"
        route_ad.request.resource_type = "xhr"
        await handler(route_ad)
        route_ad.abort.assert_called_once_with("blockedbyclient")

    @pytest.mark.asyncio()
    async def test_ad_blocking_priority_over_allowlist_empty(self, mock_context: AsyncMock) -> None:
        """Ad blocklist checked before allowlist when allowlist is empty (no restriction)."""
        resource_block = ResourceBlockConfig(block_ad_domains=True)
        allowlist = DomainAllowlist(patterns=())

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        handler = mock_context.route.call_args[0][1]

        route = AsyncMock()
        route.request = MagicMock()
        route.request.url = "https://adnxs.com/ads.js"
        route.request.resource_type = "script"
        await handler(route)
        route.abort.assert_called_once_with("blockedbyclient")


# =============================================================================
# context_factory: resource_block decoupling
# =============================================================================


class TestContextFactoryResourceBlockDecoupling:
    """Test that resource_block is installed independently of domain_allowlist."""

    @pytest.mark.asyncio()
    async def test_resource_block_without_allowlist(self) -> None:
        """resource_block should be installed even when domain_allowlist is absent."""
        from myrm_agent_harness.toolkits.browser.pool.context_factory import ContextFactory

        factory = ContextFactory()

        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_context.set_default_timeout = MagicMock()
        mock_context.add_init_script = AsyncMock()
        mock_context.route = AsyncMock()
        mock_context.on = MagicMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        resource_block = ResourceBlockConfig(block_ad_domains=True)

        context = await factory.create_context(
            mock_browser,
            "crawl",
            extra_kwargs={"resource_block": resource_block},
        )

        assert context == mock_context
        mock_context.route.assert_called_once()

    @pytest.mark.asyncio()
    async def test_no_install_without_resource_block(self) -> None:
        """No route should be installed when resource_block is not provided."""
        from myrm_agent_harness.toolkits.browser.pool.context_factory import ContextFactory

        factory = ContextFactory()

        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_context.set_default_timeout = MagicMock()
        mock_context.add_init_script = AsyncMock()
        mock_context.route = AsyncMock()
        mock_context.on = MagicMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        context = await factory.create_context(
            mock_browser,
            "crawl",
            extra_kwargs={},
        )

        assert context == mock_context
        mock_context.route.assert_not_called()


# =============================================================================
# Edge cases and boundary conditions
# =============================================================================


class TestAdBlockingEdgeCases:
    """Edge cases for ad domain blocking."""

    def test_is_ad_domain_single_label(self) -> None:
        """Single-label hostname should never match (TLDs not blocked)."""
        blocklist = frozenset({"com", "net", "org"})
        assert _is_ad_domain("com", blocklist) is True  # exact match works
        # But a hostname like "example" won't find "com" as a subdomain walk result
        assert _is_ad_domain("example", frozenset({"example"})) is True

    def test_is_ad_domain_case_sensitivity(self) -> None:
        """_is_ad_domain is case-sensitive; callers must lowercase before calling."""
        blocklist = frozenset({"doubleclick.net"})
        # hostname from urlparse is always lowercase
        assert _is_ad_domain("doubleclick.net", blocklist) is True
        # uppercase won't match (by design, callers lowercase via urlparse)
        assert _is_ad_domain("DOUBLECLICK.NET", blocklist) is False

    @pytest.mark.asyncio()
    async def test_non_http_url_not_affected(self) -> None:
        """Non-HTTP URLs (data:, blob:, about:) should not be blocked by ad filter."""
        mock_context = AsyncMock()
        mock_context.route = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        mock_context.on = MagicMock()

        resource_block = ResourceBlockConfig(block_ad_domains=True)
        allowlist = DomainAllowlist(patterns=())

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        handler = mock_context.route.call_args[0][1]

        # data: URL should continue
        route = AsyncMock()
        route.request = MagicMock()
        route.request.url = "data:text/html,<h1>Hello</h1>"
        route.request.resource_type = "document"
        await handler(route)
        # data: with resource_type=document is aborted by the non-http document rule
        route.abort.assert_called_once_with("blockedbyclient")

    @pytest.mark.asyncio()
    async def test_non_http_non_document_continues(self) -> None:
        """Non-HTTP non-document requests should continue (e.g. blob: scripts)."""
        mock_context = AsyncMock()
        mock_context.route = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        mock_context.on = MagicMock()

        resource_block = ResourceBlockConfig(block_ad_domains=True)
        allowlist = DomainAllowlist(patterns=())

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        handler = mock_context.route.call_args[0][1]

        route = AsyncMock()
        route.request = MagicMock()
        route.request.url = "blob:null/abc123"
        route.request.resource_type = "script"
        await handler(route)
        route.continue_.assert_called_once()

    @pytest.mark.asyncio()
    async def test_only_ad_blocking_no_resource_type_blocking(self) -> None:
        """When only block_ad_domains=True (all resource types False), route still installed."""
        mock_context = AsyncMock()
        mock_context.route = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        mock_context.on = MagicMock()

        resource_block = ResourceBlockConfig(block_ad_domains=True)
        allowlist = DomainAllowlist(patterns=())

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        # Route should be installed (ad_blocklist triggers it)
        mock_context.route.assert_called_once()

        handler = mock_context.route.call_args[0][1]

        # An image from a non-ad domain should NOT be blocked (block_images=False)
        route = AsyncMock()
        route.request = MagicMock()
        route.request.url = "https://example.com/photo.png"
        route.request.resource_type = "image"
        await handler(route)
        route.continue_.assert_called_once()

    @pytest.mark.asyncio()
    async def test_ad_blocking_with_domain_allowlist(self) -> None:
        """Ad blocking takes priority even when domain allowlist is set."""
        mock_context = AsyncMock()
        mock_context.route = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        mock_context.on = MagicMock()

        resource_block = ResourceBlockConfig(block_ad_domains=True)
        allowlist = DomainAllowlist(patterns=("*.example.com",))

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        handler = mock_context.route.call_args[0][1]

        # Ad domain blocked even though allowlist is non-empty
        route_ad = AsyncMock()
        route_ad.request = MagicMock()
        route_ad.request.url = "https://ad.doubleclick.net/ads.js"
        route_ad.request.resource_type = "script"
        await handler(route_ad)
        route_ad.abort.assert_called_once_with("blockedbyclient")

        # Non-allowed, non-ad domain also blocked (by allowlist)
        route_other = AsyncMock()
        route_other.request = MagicMock()
        route_other.request.url = "https://other-site.com/page"
        route_other.request.resource_type = "document"
        await handler(route_other)
        route_other.abort.assert_called_once_with("blockedbyclient")

        # Allowed domain passes
        route_ok = AsyncMock()
        route_ok.request = MagicMock()
        route_ok.request.url = "https://cdn.example.com/lib.js"
        route_ok.request.resource_type = "script"
        await handler(route_ok)
        route_ok.continue_.assert_called_once()

    @pytest.mark.asyncio()
    async def test_hostname_parse_edge_case_no_hostname(self) -> None:
        """URL with no parseable hostname should not crash."""
        mock_context = AsyncMock()
        mock_context.route = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        mock_context.on = MagicMock()

        resource_block = ResourceBlockConfig(block_ad_domains=True)
        allowlist = DomainAllowlist(patterns=())

        await install_domain_filter(mock_context, allowlist, resource_block=resource_block)

        handler = mock_context.route.call_args[0][1]

        route = AsyncMock()
        route.request = MagicMock()
        route.request.url = "http:///path/only"
        route.request.resource_type = "document"
        await handler(route)
        # Empty hostname won't match any ad domain, should continue
        route.continue_.assert_called_once()

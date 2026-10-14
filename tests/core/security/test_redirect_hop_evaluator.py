"""Private network and cloud metadata classification, with explicit-origin grants.

``evaluate_hop`` performs no DNS: it judges the host as written. ``evaluate_hop_resolved`` adds one
name lookup for local-mode policies (grants given), so a hostname that resolves to loopback or
link-local is judged as the private origin it is. Grants record origins a local-mode session was sent
to on purpose; they relax loopback / LAN / local-name rules for exactly that origin and never the
cloud metadata endpoints.
"""

from __future__ import annotations

import ipaddress
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.core.security.redirect_hop_guard import (
    HopDisposition,
    HopEvaluationResult,
    PrivateOriginGrants,
    RedirectHopEvaluator,
)

_METADATA_URLS = [
    "http://169.254.169.254/latest/meta-data/",
    "http://100.100.100.200/latest/meta-data/",
    "http://instance-data/latest/api/token",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://[::ffff:169.254.169.254]/",
]


class TestWithoutGrants:
    @pytest.mark.parametrize("url", _METADATA_URLS)
    def test_cloud_metadata_is_blocked(self, url: str) -> None:
        result = RedirectHopEvaluator().evaluate_hop(url)

        assert result.is_private is True
        assert result.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT
        assert result.matched_rule == "CLOUD_METADATA_IMDS"

    def test_subresource_block_does_not_reset_the_document(self) -> None:
        result = RedirectHopEvaluator().evaluate_hop("http://100.100.100.200/x", resource_type="fetch")

        assert result.disposition == HopDisposition.ABORT_SUBRESOURCE

    @pytest.mark.parametrize(
        ("url", "rule"),
        [
            ("http://127.0.0.1:8000/api", "PRIVATE_IPV4_127.0.0.0/8"),
            ("http://10.200.1.5/dashboard", "PRIVATE_IPV4_10.0.0.0/8"),
            ("http://172.16.10.1:3000/", "PRIVATE_IPV4_172.16.0.0/12"),
            ("http://192.168.1.1/admin", "PRIVATE_IPV4_192.168.0.0/16"),
            ("http://100.64.0.1:80/", "PRIVATE_IPV4_100.64.0.0/10"),
            ("http://localhost:5000/", "LOCAL_HOSTNAME_PATTERN"),
            ("http://app.local/", "LOCAL_HOSTNAME_PATTERN"),
            ("http://service.internal/status", "LOCAL_HOSTNAME_PATTERN"),
            ("http://[::1]:8080/", "PRIVATE_IPV6_::1/128"),
            ("http://[fd00::1234]:9000/v1", "PRIVATE_IPV6_fc00::/7"),
            ("http://[fe80::1]/", "PRIVATE_IPV6_fe80::/10"),
            ("http://[::ffff:10.0.0.5]/", "PRIVATE_IPV4_10.0.0.0/8"),
        ],
    )
    def test_private_targets_are_blocked(self, url: str, rule: str) -> None:
        result = RedirectHopEvaluator().evaluate_hop(url)

        assert result.is_private is True
        assert result.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT
        assert result.matched_rule == rule

    @pytest.mark.parametrize(
        "url",
        ["https://example.com/", "https://api.github.com/user", "http://93.184.216.34/"],
    )
    def test_public_targets_are_allowed(self, url: str) -> None:
        result = RedirectHopEvaluator().evaluate_hop(url)

        assert result.is_private is False
        assert result.disposition == HopDisposition.ALLOW
        assert result.matched_rule == "PUBLIC_TARGET"

    def test_non_http_document_is_blocked_but_about_blank_is_not(self) -> None:
        evaluator = RedirectHopEvaluator()

        assert evaluator.evaluate_hop("file:///etc/passwd").disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT
        assert evaluator.evaluate_hop("about:blank").disposition == HopDisposition.ALLOW
        assert evaluator.evaluate_hop("data:text/plain,hi", resource_type="image").disposition == HopDisposition.ALLOW


class TestGrants:
    def test_origin_is_scheme_host_and_port(self) -> None:
        grants = PrivateOriginGrants()
        grants.grant("http://localhost:3000/app/page?x=1")

        assert grants.permits("http://localhost:3000/other")
        assert grants.permits("http://LOCALHOST.:3000/")
        assert not grants.permits("http://localhost:3001/")
        assert not grants.permits("https://localhost:3000/")
        assert not grants.permits("http://127.0.0.1:3000/")

    def test_default_ports_are_implied(self) -> None:
        grants = PrivateOriginGrants()
        grants.grant("http://intranet.local/")
        grants.grant("https://vault.local/")

        assert grants.permits("http://intranet.local:80/x")
        assert grants.permits("https://vault.local:443/x")
        assert not grants.permits("https://intranet.local/")

    @pytest.mark.parametrize("url", ["about:blank", "file:///etc/passwd", "http://", "http://x:99999/", "garbage"])
    def test_urls_without_a_usable_origin_grant_nothing(self, url: str) -> None:
        grants = PrivateOriginGrants()
        grants.grant(url)

        assert not grants.permits(url)
        assert not grants.permits("http://localhost/")


class TestWithGrants:
    @staticmethod
    def _evaluator(granted: str) -> RedirectHopEvaluator:
        grants = PrivateOriginGrants()
        grants.grant(granted)
        return RedirectHopEvaluator(grants=grants)

    @pytest.mark.parametrize(
        "granted",
        [
            "http://localhost:3000/",
            "http://127.0.0.1:8080/",
            "http://192.168.1.20/",
            "http://[::1]:9000/",
            "http://nas.local/",
        ],
    )
    def test_granted_private_origin_is_allowed(self, granted: str) -> None:
        result = self._evaluator(granted).evaluate_hop(granted + "page")

        assert result.disposition == HopDisposition.ALLOW
        assert result.is_private is True
        assert result.matched_rule == "EXPLICIT_PRIVATE_ORIGIN"

    @pytest.mark.parametrize("resource_type", ["document", "xhr", "script"])
    def test_other_private_origins_stay_blocked(self, resource_type: str) -> None:
        evaluator = self._evaluator("http://localhost:3000/")

        for hop in ("http://localhost:3001/", "http://127.0.0.1:3000/", "http://10.0.0.5/", "http://db.internal/"):
            assert evaluator.evaluate_hop(hop, resource_type=resource_type).disposition != HopDisposition.ALLOW

    @pytest.mark.parametrize("metadata_url", _METADATA_URLS)
    def test_cloud_metadata_is_blocked_even_when_granted(self, metadata_url: str) -> None:
        result = self._evaluator(metadata_url).evaluate_hop(metadata_url)

        assert result.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT
        assert result.matched_rule == "CLOUD_METADATA_IMDS"

    def test_public_targets_are_unaffected_by_grants(self) -> None:
        result = self._evaluator("http://localhost:3000/").evaluate_hop("https://example.com/")

        assert result.matched_rule == "PUBLIC_TARGET"


_RESOLVE = "myrm_agent_harness.core.security.redirect_hop_guard.hop_evaluator.resolve_addresses"


def _answers(*addresses: str) -> AsyncMock:
    return AsyncMock(return_value=tuple(ipaddress.ip_address(address) for address in addresses))


async def _resolved(
    url: str, *addresses: str, granted: str | None = None, resource_type: str = "document"
) -> HopEvaluationResult:
    grants = PrivateOriginGrants()
    if granted is not None:
        grants.grant(granted)
    with patch(_RESOLVE, _answers(*addresses)):
        return await RedirectHopEvaluator(grants=grants).evaluate_hop_resolved(url, resource_type)


class TestResolvedHostnames:
    """A hostname is the same origin as the address it resolves to; only loopback, link-local and metadata count."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "address",
        ["127.0.0.1", "127.8.9.10", "::1", "::ffff:127.0.0.1", "169.254.1.1", "fe80::1", "0.0.0.0", "::"],  # noqa: S104
    )
    async def test_a_hostname_resolving_to_a_local_address_is_blocked(self, address: str) -> None:
        result = await _resolved("http://rebind.example:3000/", address)

        assert result.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT
        assert result.matched_rule == "RESOLVES_TO_LOCAL_ADDRESS"
        assert "rebind.example" in result.reason
        assert "loopback or link-local" in result.reason

    @pytest.mark.asyncio
    async def test_a_subresource_is_aborted_without_resetting_the_document(self) -> None:
        result = await _resolved("http://rebind.example/", "127.0.0.1", resource_type="fetch")

        assert result.disposition == HopDisposition.ABORT_SUBRESOURCE

    @pytest.mark.asyncio
    async def test_any_local_address_in_the_answer_blocks(self) -> None:
        result = await _resolved("http://mixed.example/", "93.184.216.34", "127.0.0.1")

        assert result.matched_rule == "RESOLVES_TO_LOCAL_ADDRESS"

    @pytest.mark.asyncio
    async def test_an_origin_navigated_to_explicitly_stays_allowed(self) -> None:
        result = await _resolved("http://app.example:3000/x", "127.0.0.1", granted="http://app.example:3000/")

        assert result.disposition == HopDisposition.ALLOW
        assert result.matched_rule == "EXPLICIT_PRIVATE_ORIGIN"

    @pytest.mark.asyncio
    async def test_a_grant_covers_exactly_its_origin(self) -> None:
        result = await _resolved("http://app.example:3001/", "127.0.0.1", granted="http://app.example:3000/")

        assert result.matched_rule == "RESOLVES_TO_LOCAL_ADDRESS"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("address", ["169.254.169.254", "100.100.100.200", "::ffff:169.254.169.254"])
    async def test_cloud_metadata_behind_a_hostname_is_blocked_even_when_granted(self, address: str) -> None:
        result = await _resolved("http://creds.example/", address, granted="http://creds.example/")

        assert result.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT
        assert result.matched_rule == "CLOUD_METADATA_IMDS"
        assert "metadata" in result.reason

    @pytest.mark.asyncio
    async def test_metadata_later_in_the_answer_is_not_masked_by_a_granted_loopback(self) -> None:
        result = await _resolved("http://both.example/", "127.0.0.1", "169.254.169.254", granted="http://both.example/")

        assert result.matched_rule == "CLOUD_METADATA_IMDS"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "address",
        ["93.184.216.34", "2606:2800:220:1::1", "10.0.0.5", "172.20.0.9", "192.168.1.9", "100.64.0.7", "198.18.1.234"],
    )
    async def test_public_proxy_and_lan_ranges_are_not_judged(self, address: str) -> None:
        """Fake-IP proxies and VPNs hand out RFC 1918 / CGNAT / benchmarking ranges for public names."""
        result = await _resolved("http://site.example/", address)

        assert result.disposition == HopDisposition.ALLOW
        assert result.matched_rule == "PUBLIC_TARGET"

    @pytest.mark.asyncio
    async def test_a_lookup_that_found_nothing_changes_nothing(self) -> None:
        result = await _resolved("http://site.example/")

        assert result.matched_rule == "PUBLIC_TARGET"

    @pytest.mark.asyncio
    async def test_no_lookup_without_grants(self) -> None:
        """Cloud policy resolves and pins elsewhere; the evaluator stays literal there."""
        with patch(_RESOLVE, _answers("127.0.0.1")) as resolver:
            result = await RedirectHopEvaluator().evaluate_hop_resolved("http://rebind.example/")

        resolver.assert_not_called()
        assert result.matched_rule == "PUBLIC_TARGET"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://93.184.216.34/",
            "http://[2606:2800:220:1::1]/",
            "http://localhost:3000/",
            "http://app.local/",
            "http://169.254.169.254/",
            "http://metadata.google.internal/",
            "file:///etc/passwd",
            "about:blank",
        ],
    )
    async def test_only_plain_hostnames_are_looked_up(self, url: str) -> None:
        with patch(_RESOLVE, _answers("127.0.0.1")) as resolver:
            literal = RedirectHopEvaluator(grants=PrivateOriginGrants()).evaluate_hop(url)
            resolved = await RedirectHopEvaluator(grants=PrivateOriginGrants()).evaluate_hop_resolved(url)

        resolver.assert_not_called()
        assert resolved == literal

    @pytest.mark.asyncio
    async def test_the_host_is_normalised_before_the_lookup(self) -> None:
        resolver = _answers("203.0.113.9")
        with patch(_RESOLVE, resolver):
            await RedirectHopEvaluator(grants=PrivateOriginGrants()).evaluate_hop_resolved("http://Site.Example./x")

        resolver.assert_awaited_once_with("site.example")

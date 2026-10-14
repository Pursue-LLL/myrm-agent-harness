"""Literal-host private network and cloud metadata classification, with explicit-origin grants.

The evaluator performs no DNS: it judges the host as written. Grants record origins a local-mode
session was sent to on purpose; they relax loopback / LAN / local-name rules for exactly that origin
and never the cloud metadata endpoints.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.redirect_hop_guard import (
    HopDisposition,
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

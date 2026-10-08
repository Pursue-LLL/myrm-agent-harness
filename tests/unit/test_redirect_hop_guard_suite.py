"""Unit tests for Redirect Private Address Hop Revalidation Suite.

Verifies hop-by-hop private network and metadata revalidation, document-level
tab reset to about:blank, violation audit recording, and policy configurations.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.redirect_hop_guard import (
    HopDisposition,
    RedirectHopEvaluator,
    RedirectHopGuardConfig,
    RedirectHopGuardFacade,
)


class DummyRequest:
    def __init__(self, url: str, resource_type: str = "document") -> None:
        self.url = url
        self.resource_type = resource_type


class DummyRoute:
    def __init__(self, request: DummyRequest) -> None:
        self.request = request
        self.aborted: bool = False
        self.abort_code: str | None = None
        self.continued: bool = False

    async def abort(self, error_code: str | None = None) -> None:
        self.aborted = True
        self.abort_code = error_code

    async def continue_(self) -> None:
        self.continued = True


class DummyPage:
    def __init__(self) -> None:
        self.navigated_urls: list[str] = []

    async def goto(self, url: str) -> None:
        self.navigated_urls.append(url)


def test_evaluator_blocks_cloud_metadata_imds() -> None:
    evaluator = RedirectHopEvaluator()

    # AWS/GCP/Azure IMDS IPv4
    res1 = evaluator.evaluate_hop("http://169.254.169.254/latest/meta-data/", resource_type="document")
    assert res1.is_private is True
    assert res1.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT
    assert "CLOUD_METADATA_IMDS" in res1.matched_rule

    # Alibaba Cloud IMDS
    res2 = evaluator.evaluate_hop("http://100.100.100.200/latest/meta-data/", resource_type="fetch")
    assert res2.is_private is True
    assert res2.disposition == HopDisposition.ABORT_SUBRESOURCE
    assert res2.matched_rule == "CLOUD_METADATA_IMDS"

    # instance-data hostname
    res3 = evaluator.evaluate_hop("http://instance-data/latest/api/token", resource_type="document")
    assert res3.is_private is True
    assert res3.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT


def test_evaluator_blocks_rfc1918_and_loopback_and_cgnat() -> None:
    evaluator = RedirectHopEvaluator()

    targets = [
        ("http://127.0.0.1:8000/api", "PRIVATE_IPV4_127.0.0.0/8"),
        ("http://10.200.1.5/dashboard", "PRIVATE_IPV4_10.0.0.0/8"),
        ("http://172.16.10.1:3000/", "PRIVATE_IPV4_172.16.0.0/12"),
        ("http://192.168.1.1/admin", "PRIVATE_IPV4_192.168.0.0/16"),
        ("http://100.64.0.1:80/", "PRIVATE_IPV4_100.64.0.0/10"),
        ("http://localhost:5000/", "LOCAL_HOSTNAME_PATTERN"),
        ("http://app.local/", "LOCAL_HOSTNAME_PATTERN"),
        ("http://service.internal/status", "LOCAL_HOSTNAME_PATTERN"),
    ]

    for url, expected_rule in targets:
        result = evaluator.evaluate_hop(url, resource_type="document")
        assert result.is_private is True, f"URL {url} should be detected as private"
        assert result.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT
        assert expected_rule in result.matched_rule, f"URL {url} expected rule {expected_rule}, got {result.matched_rule}"


def test_evaluator_blocks_ipv6_private_and_loopback() -> None:
    evaluator = RedirectHopEvaluator()

    # IPv6 loopback ::1
    res1 = evaluator.evaluate_hop("http://[::1]:8080/", resource_type="document")
    assert res1.is_private is True
    assert res1.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT

    # Unique Local Address (fc00::/7)
    res2 = evaluator.evaluate_hop("http://[fd00::1234]:9000/v1", resource_type="xhr")
    assert res2.is_private is True
    assert res2.disposition == HopDisposition.ABORT_SUBRESOURCE

    # Link-local (fe80::/10)
    res3 = evaluator.evaluate_hop("http://[fe80::1]/", resource_type="document")
    assert res3.is_private is True
    assert res3.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT


def test_evaluator_allows_public_urls() -> None:
    evaluator = RedirectHopEvaluator()

    public_urls = [
        "https://example.com/",
        "https://api.github.com/user",
        "https://google.com/search?q=test",
        "http://93.184.216.34/",  # example.com literal IP
    ]

    for url in public_urls:
        result = evaluator.evaluate_hop(url, resource_type="document")
        assert result.is_private is False
        assert result.disposition == HopDisposition.ALLOW
        assert result.matched_rule == "PUBLIC_TARGET"


def test_evaluator_allow_private_networks_policy() -> None:
    config = RedirectHopGuardConfig(allow_private_networks=True)
    evaluator = RedirectHopEvaluator(config)

    result = evaluator.evaluate_hop("http://192.168.1.1/admin", resource_type="document")
    assert result.is_private is False
    assert result.disposition == HopDisposition.ALLOW
    assert result.matched_rule == "ALLOW_POLICY_ENABLED"


@pytest.mark.asyncio
async def test_interceptor_aborts_and_resets_tab_on_document_violation() -> None:
    facade = RedirectHopGuardFacade()
    page = DummyPage()

    # Document redirect to AWS IMDS
    req = DummyRequest("http://169.254.169.254/latest/meta-data/", resource_type="document")
    route = DummyRoute(req)

    result, audit = await facade.handle_route(route=route, page=page, initial_url="https://example.com/redirector")

    assert result.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT
    assert route.aborted is True
    assert route.abort_code == "blockedbyclient"
    assert route.continued is False
    assert page.navigated_urls == ["about:blank"]
    assert audit is not None
    assert audit.initial_url == "https://example.com/redirector"
    assert audit.hop_url == "http://169.254.169.254/latest/meta-data/"
    assert audit.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT

    violations = facade.get_violations()
    assert len(violations) == 1
    assert violations[0] == audit


@pytest.mark.asyncio
async def test_interceptor_subresource_abort_without_page_reset() -> None:
    facade = RedirectHopGuardFacade()
    page = DummyPage()

    # Subresource fetch to internal network
    req = DummyRequest("http://10.0.0.1/sensitive.json", resource_type="fetch")
    route = DummyRoute(req)

    result, audit = await facade.handle_route(route=route, page=page, initial_url="https://example.com/")

    assert result.disposition == HopDisposition.ABORT_SUBRESOURCE
    assert route.aborted is True
    assert route.continued is False
    assert len(page.navigated_urls) == 0  # No about:blank reset for subresources
    assert audit is not None
    assert audit.disposition == HopDisposition.ABORT_SUBRESOURCE

    facade.clear_violations()
    assert len(facade.get_violations()) == 0


@pytest.mark.asyncio
async def test_interceptor_allows_public_hop() -> None:
    facade = RedirectHopGuardFacade()
    page = DummyPage()

    req = DummyRequest("https://cdn.example.com/lib.js", resource_type="script")
    route = DummyRoute(req)

    result, audit = await facade.handle_route(route=route, page=page, initial_url="https://example.com/")

    assert result.disposition == HopDisposition.ALLOW
    assert route.aborted is False
    assert route.continued is True
    assert audit is None
    assert len(facade.get_violations()) == 0

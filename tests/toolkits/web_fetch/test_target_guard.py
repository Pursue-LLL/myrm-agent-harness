"""FetchTargetGuard policy matrix: which URLs a web_fetch request may contact.

Cloud policy (no private networks): every address must be public. Local policy: the origin the fetch
was aimed at may be private; any other private origin, legacy-spelled loopback and hostnames that
resolve to loopback, link-local or metadata included, and cloud metadata never may. The local
policy's name lookup is answered from a table so the tests never touch the network.
"""

from __future__ import annotations

import ipaddress

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.core.security.guards.url_allowlist import URLAllowlistGuard
from myrm_agent_harness.toolkits.web_fetch.fetchers.target_guard import FetchTargetGuard, _canonical_url

_PUBLIC_ADDRESS = "93.184.216.34"
_DNS_ANSWERS: dict[str, str | None] = {
    "rebind.example": "127.0.0.1",
    "linklocal.example": "169.254.10.10",
    "creds.example": "169.254.169.254",
    "proxied.example": "198.18.0.7",
    "dead.example": None,
}


@pytest.fixture(autouse=True)
def _name_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answer(hostname: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        address = _DNS_ANSWERS.get(hostname, _PUBLIC_ADDRESS)
        return () if address is None else (ipaddress.ip_address(address),)

    monkeypatch.setattr("myrm_agent_harness.core.security.redirect_hop_guard.hop_evaluator.resolve_addresses", answer)


def _local(requested: str, allowed_hosts: list[str] | None = None) -> FetchTargetGuard:
    return FetchTargetGuard(requested_url=requested, allow_private_networks=True, allowed_hosts=allowed_hosts or [])


def _cloud(requested: str = "https://example.com/", allowed_hosts: list[str] | None = None) -> FetchTargetGuard:
    return FetchTargetGuard(requested_url=requested, allow_private_networks=False, allowed_hosts=allowed_hosts or [])


@pytest.mark.asyncio
class TestLocalPolicy:
    @pytest.mark.parametrize(
        "requested",
        [
            "http://localhost:3000/app",
            "http://127.0.0.1:8080/",
            "http://192.168.1.20/dashboard",
            "http://[::1]:9000/",
            "http://devbox.local:5173/",
        ],
    )
    async def test_requested_private_origin_is_reachable(self, requested: str) -> None:
        guard = _local(requested)

        assert await guard.pin(requested) == (requested, {})

    async def test_same_origin_redirect_is_reachable(self) -> None:
        guard = _local("http://localhost:3000/start")

        await guard.pin("http://localhost:3000/final")

    @pytest.mark.parametrize(
        "hop",
        [
            "http://localhost:4000/",  # other port = other origin
            "https://localhost:3000/",  # other scheme = other origin
            "http://127.0.0.1:3000/",  # other host spelling = other origin
            "http://10.0.0.5/",
            "http://192.168.0.1/admin",
            "http://[::1]:3000/",
            "http://[::ffff:10.0.0.5]/",
            "http://printer.local/",
        ],
    )
    async def test_other_private_origins_are_blocked(self, hop: str) -> None:
        guard = _local("http://localhost:3000/start")

        with pytest.raises(SSRFSecurityError):
            await guard.pin(hop)

    @pytest.mark.parametrize(
        "spelling",
        ["http://2130706433:7000/", "http://0x7f.0.0.1:7000/", "http://0177.0.0.1:7000/", "http://127.1:7000/"],
    )
    async def test_legacy_loopback_spellings_are_judged_as_the_address_they_dial(self, spelling: str) -> None:
        guard = _local("http://localhost:3000/start")

        with pytest.raises(SSRFSecurityError):
            await guard.pin(spelling)

    async def test_requested_legacy_spelling_grants_its_canonical_origin(self) -> None:
        guard = _local("http://2130706433:7000/page")

        await guard.pin("http://127.0.0.1:7000/other")

    @pytest.mark.parametrize(
        "metadata",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://[::ffff:169.254.169.254]/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://2852039166/",  # 169.254.169.254 as a decimal integer
        ],
    )
    async def test_cloud_metadata_is_never_reachable_not_even_when_requested(self, metadata: str) -> None:
        guard = _local(metadata)

        with pytest.raises(SSRFSecurityError):
            await guard.pin(metadata)

    @pytest.mark.parametrize(
        "hop",
        [
            "http://rebind.example/",  # resolves to 127.0.0.1
            "http://linklocal.example:8080/",
            "http://creds.example/latest/meta-data/",  # resolves to 169.254.169.254
        ],
    )
    async def test_hostnames_resolving_to_a_local_address_are_blocked_as_redirect_hops(self, hop: str) -> None:
        guard = _local("http://localhost:3000/start")

        with pytest.raises(SSRFSecurityError, match="resolves to"):
            await guard.pin(hop)

    async def test_a_requested_hostname_resolving_to_loopback_is_reachable(self) -> None:
        guard = _local("http://rebind.example:3000/start")

        await guard.pin("http://rebind.example:3000/final")

    async def test_cloud_metadata_behind_a_hostname_is_never_reachable_not_even_when_requested(self) -> None:
        guard = _local("http://creds.example/")

        with pytest.raises(SSRFSecurityError, match="metadata"):
            await guard.pin("http://creds.example/")

    @pytest.mark.parametrize("hop", ["http://proxied.example/", "http://dead.example/"])
    async def test_what_a_proxy_hands_out_or_a_dns_that_cannot_answer_does_not_block(self, hop: str) -> None:
        guard = _local("http://localhost:3000/start")

        assert await guard.pin(hop) == (hop, {})

    @pytest.mark.parametrize("public", ["http://8.8.8.8/", "https://example.com/path", "https://sub.example.org:8443/"])
    async def test_public_targets_are_reachable(self, public: str) -> None:
        guard = _local("http://localhost:3000/start")

        assert await guard.pin(public) == (public, {})

    @pytest.mark.parametrize(
        "url",
        ["file:///etc/passwd", "ftp://example.com/", "http://example.com\t@169.254.169.254/", "http://", "http://\\x"],
    )
    async def test_unusable_urls_are_blocked(self, url: str) -> None:
        guard = _local("http://localhost:3000/start")

        with pytest.raises(SSRFSecurityError):
            await guard.pin(url)

    async def test_allowed_internal_host_is_reachable_as_a_redirect_hop(self) -> None:
        guard = _local("http://localhost:3000/start", allowed_hosts=["10.0.0.5"])

        await guard.pin("http://10.0.0.5/api")

    async def test_skill_domain_allowlist_still_applies_to_the_requested_origin(self) -> None:
        guard = _local("http://localhost:3000/start")

        with URLAllowlistGuard.apply(["example.com"]), pytest.raises(SSRFSecurityError):
            await guard.pin("http://localhost:3000/start")

    async def test_pin_never_adds_a_host_header(self) -> None:
        guard = _local("http://localhost:3000/start")

        _url, headers = await guard.pin("https://example.com/")

        assert headers == {}


@pytest.mark.asyncio
class TestCloudPolicy:
    @pytest.mark.parametrize(
        "hop",
        ["http://127.0.0.1/", "http://localhost/", "http://[::1]/", "http://10.0.0.5/", "http://169.254.169.254/"],
    )
    async def test_private_targets_are_blocked(self, hop: str) -> None:
        with pytest.raises(SSRFSecurityError):
            await _cloud().pin(hop)

    async def test_requesting_a_private_origin_does_not_grant_it(self) -> None:
        guard = _cloud(requested="http://127.0.0.1:3000/")

        with pytest.raises(SSRFSecurityError):
            await guard.pin("http://127.0.0.1:3000/")

    async def test_allowed_internal_host_is_reachable(self) -> None:
        guard = _cloud(allowed_hosts=["127.0.0.1"])

        assert await guard.pin("http://127.0.0.1:3000/") == ("http://127.0.0.1:3000/", {})

    async def test_public_literal_is_reachable(self) -> None:
        url, _headers = await _cloud().pin("http://8.8.8.8/")

        assert "8.8.8.8" in url


class TestCanonicalUrl:
    @pytest.mark.parametrize(
        ("spelled", "canonical"),
        [
            ("http://2130706433:80/x", "http://127.0.0.1:80/x"),
            ("http://0x7f.1/", "http://127.0.0.1/"),
            ("https://0177.0.0.1:8443/a?b=1", "https://127.0.0.1:8443/a?b=1"),
        ],
    )
    def test_legacy_ipv4_hosts_are_rewritten(self, spelled: str, canonical: str) -> None:
        assert _canonical_url(spelled) == canonical

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:80/",
            "https://example.com/a",
            "http://[::1]:80/",
            "http://localhost:3000/",
            "http://x:99999/",
        ],
    )
    def test_everything_else_is_left_alone(self, url: str) -> None:
        assert _canonical_url(url) == url

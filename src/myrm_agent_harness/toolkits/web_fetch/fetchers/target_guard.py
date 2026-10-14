"""SSRF guard for one web_fetch request, shared by the tiers that follow redirects.

[INPUT]
- core.security.guards.ssrf::async_pin_url, SSRFSecurityError (POS: DNS-validated URL checks + audit)
- core.security.guards.url_allowlist::URLAllowlistGuard (POS: skill DLP domain allowlist)
- core.security.redirect_hop_guard::RedirectHopEvaluator, PrivateOriginGrants (POS: private network and cloud metadata classification; local mode also judges a hostname by what it resolves to)
- core.security.audit::record_decision (POS: security decision audit trail)
- utils.url_syntax::parse_outbound_hostname (POS: outbound URL syntax check, no hostname blocklist)

[OUTPUT]
- FetchTargetGuard: pins every URL one fetch contacts (the requested URL and each redirect hop)

[POS]
Per-fetch SSRF policy for the web_fetch tiers that follow redirects. Cloud policy resolves the host
and requires every address to be public. Local policy (``allow_private_networks``) classifies the
host as written and by its DNS answer, but only loopback, link-local and metadata answers count: the
user's own resolver is not otherwise second-guessed, the origin the fetch was aimed at may be
private, any other private origin reached through a redirect may not, and cloud metadata endpoints
never may. Exact hosts listed in ``MYRM_ALLOWED_INTERNAL_HOSTS`` stay reachable under
both policies.
"""

from __future__ import annotations

import logging
import socket
from urllib.parse import urlsplit, urlunsplit

from myrm_agent_harness.core.security.audit import record_decision
from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError, async_pin_url
from myrm_agent_harness.core.security.guards.url_allowlist import URLAllowlistGuard
from myrm_agent_harness.core.security.redirect_hop_guard import (
    HopDisposition,
    PrivateOriginGrants,
    RedirectHopEvaluator,
)
from myrm_agent_harness.utils.url_syntax import parse_outbound_hostname

logger = logging.getLogger(__name__)


def _canonical_url(url: str) -> str:
    """Spell a legacy numeric IPv4 host (``2130706433``, ``0x7f.1``) the way HTTP clients dial it.

    Literal classification would otherwise read such a host as a public name while the client
    connects to loopback.
    """
    parts = urlsplit(url)
    host = parts.hostname
    if host is None:
        return url
    try:
        dotted = socket.inet_ntoa(socket.inet_aton(host))
        port = f":{parts.port}" if parts.port else ""
    except (OSError, ValueError):
        return url
    return url if dotted == host else urlunsplit(parts._replace(netloc=f"{dotted}{port}"))


class FetchTargetGuard:
    """Guard bound to one fetch; ``pin`` raises ``SSRFSecurityError`` for a URL the policy rejects."""

    def __init__(self, *, requested_url: str, allow_private_networks: bool, allowed_hosts: list[str]) -> None:
        self._allowed_hosts = allowed_hosts
        self._local_policy: RedirectHopEvaluator | None = None
        if allow_private_networks:
            grants = PrivateOriginGrants()
            grants.grant(_canonical_url(requested_url))
            self._local_policy = RedirectHopEvaluator(grants=grants)

    async def pin(self, url: str) -> tuple[str, dict[str, str]]:
        """Return the URL to request and the extra headers it needs (DNS-pinned under the cloud policy)."""
        if self._local_policy is None:
            return await async_pin_url(url, self._allowed_hosts)

        hostname, error = parse_outbound_hostname(url)
        if hostname is None:
            raise SSRFSecurityError(error)
        URLAllowlistGuard.check(hostname)
        if hostname not in self._allowed_hosts:
            verdict = await self._local_policy.evaluate_hop_resolved(_canonical_url(url))
            if verdict.disposition != HopDisposition.ALLOW:
                logger.warning("SSRF blocked request: %s — %s", url, verdict.reason)
                record_decision("ssrf", "SSRF_BLOCKED", f"{url}: {verdict.reason}")
                raise SSRFSecurityError(f"Access to internal network is blocked for security reasons. {verdict.reason}")
        return url, {}

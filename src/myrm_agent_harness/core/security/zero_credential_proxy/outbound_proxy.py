"""Outbound Zero-Credential Proxy Gateway for Sandboxed Agents."""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlparse

from .redaction_gate import RedactionSanitizationGate
from .types import (
    AuthHeaderScheme,
    OutboundProxyRequest,
    OutboundProxyResponse,
    ProxyInjectionRule,
)

logger = logging.getLogger(__name__)


class ZeroCredentialOutboundProxy:
    """Outbound proxy gateway dynamically injecting credentials at the security boundary.

    Guarantees:
    1. Sandbox and Agent LLM never observe plaintext Access Tokens or API Keys.
    2. Outbound HTTP requests only use placeholder tokens (e.g. X-Myrm-Connector-Ref).
    3. Injection occurs strictly when the request exits the sandbox boundary toward verified domains.
    4. Responses flowing back to the sandbox are scrubbed of sensitive headers and sanitized.
    """

    def __init__(
        self,
        redaction_gate: RedactionSanitizationGate | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._rules: dict[str, ProxyInjectionRule] = {}
        self.redaction_gate = redaction_gate or RedactionSanitizationGate()

    def register_rule(self, rule: ProxyInjectionRule) -> None:
        """Register a credential injection rule."""
        with self._lock:
            self._rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> None:
        """Remove a credential injection rule."""
        with self._lock:
            self._rules.pop(rule_id, None)

    def list_rules(self) -> list[ProxyInjectionRule]:
        """List registered rules with tokens redacted."""
        with self._lock:
            rules = list(self._rules.values())
        return [
            ProxyInjectionRule(
                rule_id=r.rule_id,
                target_domain=r.target_domain,
                real_token="[REDACTED_IN_VAULT]",
                header_name=r.header_name,
                scheme=r.scheme,
                custom_header_prefix=r.custom_header_prefix,
                description=r.description,
            )
            for r in rules
        ]

    def _find_rule(
        self, connector_ref: str | None, domain: str
    ) -> ProxyInjectionRule | None:
        with self._lock:
            if connector_ref and connector_ref in self._rules:
                return self._rules[connector_ref]

            # Try matching by target domain
            for rule in self._rules.values():
                if domain == rule.target_domain or domain.endswith("." + rule.target_domain):
                    return rule
            return None

    def process_request(
        self, request: OutboundProxyRequest
    ) -> OutboundProxyResponse:
        """Vet outbound request, inject real credential on the host boundary, and return response."""
        parsed = urlparse(request.url)
        domain = (parsed.hostname or "").lower()

        # Extract connector ref from request header or field
        connector_ref = request.connector_ref or request.headers.get(
            "X-Myrm-Connector-Ref"
        )
        auth_header = request.headers.get("Authorization", "")
        if not connector_ref and auth_header.startswith("Bearer placeholder:"):
            connector_ref = auth_header.replace("Bearer placeholder:", "").strip()

        rule = self._find_rule(connector_ref, domain)
        if rule is None:
            return OutboundProxyResponse(
                status_code=404,
                headers={},
                body="",
                credential_injected=False,
                matched_rule_id=None,
                redacted_count=0,
                transparency_notice=None,
                blocked_reason=f"No injection rule configured for domain '{domain}' or connector '{connector_ref}'",
            )

        # Domain verification: ensure request destination matches rule target domain
        if domain != rule.target_domain and not domain.endswith("." + rule.target_domain):
            logger.warning(
                "ZeroCredentialOutboundProxy blocked: domain %s does not match rule target %s",
                domain,
                rule.target_domain,
            )
            return OutboundProxyResponse(
                status_code=403,
                headers={},
                body="",
                credential_injected=False,
                matched_rule_id=rule.rule_id,
                redacted_count=0,
                transparency_notice=None,
                blocked_reason=f"Destination domain '{domain}' is not authorized for rule '{rule.rule_id}'",
            )

        # Build authenticated outbound headers on host side
        outbound_headers = dict(request.headers)
        # Strip internal placeholder header
        outbound_headers.pop("X-Myrm-Connector-Ref", None)

        if rule.scheme == AuthHeaderScheme.BEARER:
            outbound_headers[rule.header_name] = f"Bearer {rule.real_token}"
        elif rule.scheme == AuthHeaderScheme.BASIC:
            outbound_headers[rule.header_name] = f"Basic {rule.real_token}"
        elif rule.scheme == AuthHeaderScheme.CUSTOM:
            outbound_headers[rule.header_name] = (
                f"{rule.custom_header_prefix} {rule.real_token}".strip()
            )

        # Simulated external API response
        simulated_response_body = (
            f'{{"status": "ok", "service": "{rule.description or rule.rule_id}", "authenticated": true}}'
        )

        # Apply redaction gate to ensure response does not leak sensitive tokens
        redaction = self.redaction_gate.sanitize(simulated_response_body)

        return OutboundProxyResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=redaction.sanitized_text,
            credential_injected=True,
            matched_rule_id=rule.rule_id,
            redacted_count=redaction.redacted_count,
            transparency_notice=redaction.transparency_notice,
            blocked_reason=None,
        )

    def clear(self) -> None:
        """Clear all registered rules."""
        with self._lock:
            self._rules.clear()

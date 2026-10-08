"""Outbound Egress Secret Interceptor for zero-context credential replacement.

[INPUT]
- Content string with placeholder references, target egress host, EgressBoundSecretVault

[OUTPUT]
- SecretInjectionResult with plaintext secrets substituted strictly for authorized destination hosts.
- EgressHostMismatchError raised if destination host is not authorized for any referenced handle.

[POS]
- Harness core security module inspired by OpenClaw 2.0 (secret-broker.ts).
- Intercepts egress HTTP headers/payloads at outbound dispatch, keeping model context 100% credential-free.
"""

from __future__ import annotations

import re

from myrm_agent_harness.core.security.secret_broker.types import (
    SecretInjectionResult,
)
from myrm_agent_harness.core.security.secret_broker.vault import EgressBoundSecretVault

# Pattern matching opaque placeholder handles like {{SECRET_VAULT:hnd_a1b2c3d4}}
_PLACEHOLDER_REGEX = re.compile(r"\{\{SECRET_VAULT:(?P<handle_id>hnd_[a-zA-Z0-9_]+)\}\}")


class EgressSecretInterceptor:
    """Interceptor that substitutes credential handles with real secrets upon egress HTTP dispatch."""

    def __init__(self, vault: EgressBoundSecretVault) -> None:
        self._vault = vault

    def extract_handles(self, content: str) -> list[str]:
        """Extract all unique secret handle IDs present in the given content."""
        if not content:
            return []
        matches = _PLACEHOLDER_REGEX.findall(content)
        return list(dict.fromkeys(matches))

    def has_placeholders(self, content: str) -> bool:
        """Check whether content contains any secret placeholders."""
        if not content:
            return False
        return _PLACEHOLDER_REGEX.search(content) is not None

    def inject_secrets(self, content: str, target_host: str) -> SecretInjectionResult:
        """Replace all secret placeholders in content with resolved credentials for target_host.

        Raises:
            EgressHostMismatchError: If any handle in content is not bound to target_host.
            KeyError: If any handle is not found in the vault.
        """
        if not content:
            return SecretInjectionResult(
                resolved_content="",
                replacements_count=0,
                target_host=target_host,
                authorized=True,
            )

        handles = self.extract_handles(content)
        if not handles:
            return SecretInjectionResult(
                resolved_content=content,
                replacements_count=0,
                target_host=target_host,
                authorized=True,
            )

        # Pre-resolve and validate all handles against target_host before modifying content
        replacements: dict[str, str] = {}
        for handle_id in handles:
            secret_value = self._vault.resolve_secret_for_host(handle_id, target_host)
            replacements[handle_id] = secret_value

        # Substitute each placeholder
        def _replace_match(match: re.Match[str]) -> str:
            hid = match.group("handle_id")
            return replacements.get(hid, match.group(0))

        resolved = _PLACEHOLDER_REGEX.sub(_replace_match, content)
        count = len(handles)

        return SecretInjectionResult(
            resolved_content=resolved,
            replacements_count=count,
            target_host=target_host,
            authorized=True,
        )

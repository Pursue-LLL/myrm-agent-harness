"""Placeholder Registry generating and managing domain-bound random placeholders."""

from __future__ import annotations

import secrets
from urllib.parse import urlparse

from .types import BoundCredentialSpec


class PlaceholderRegistry:
    """Manages high-entropy single-destination placeholders bound strictly to specific hosts.

    Prevents credential exfiltration: the placeholder is non-sensitive in sandbox env,
    and attempting to send it to any host other than target_host is immediately rejected.
    """

    def __init__(self) -> None:
        self._by_host: dict[str, BoundCredentialSpec] = {}
        self._by_placeholder: dict[str, BoundCredentialSpec] = {}

    def _normalize_host(self, host_or_url: str) -> str:
        """Extract clean lowercased hostname."""
        raw = host_or_url.strip().lower()
        if "://" in raw:
            parsed = urlparse(raw)
            return (parsed.hostname or raw).lower()
        if ":" in raw:
            return raw.split(":", 1)[0]
        return raw

    def register_credential(
        self,
        target_host: str,
        real_secret: str,
        auth_header_name: str = "Authorization",
        auth_header_template: str = "Bearer {secret}",
    ) -> BoundCredentialSpec:
        """Register a real credential and bind a unique random placeholder to the host."""
        clean_host = self._normalize_host(target_host)
        placeholder = f"myrm_cred_{secrets.token_hex(8)}"

        spec = BoundCredentialSpec(
            target_host=clean_host,
            auth_header_name=auth_header_name.strip(),
            auth_header_template=auth_header_template.strip(),
            real_secret=real_secret.strip(),
            placeholder=placeholder,
            is_active=True,
        )
        self._by_host[clean_host] = spec
        self._by_placeholder[placeholder] = spec
        return spec

    def get_by_host(self, target_host: str) -> BoundCredentialSpec | None:
        """Retrieve credential specification bound to host."""
        clean_host = self._normalize_host(target_host)
        spec = self._by_host.get(clean_host)
        return spec if (spec and spec.is_active) else None

    def get_by_placeholder(self, placeholder: str) -> BoundCredentialSpec | None:
        """Retrieve credential specification matching placeholder."""
        spec = self._by_placeholder.get(placeholder.strip())
        return spec if (spec and spec.is_active) else None

    def is_placeholder(self, token_str: str) -> bool:
        """Check whether token_str is a registered placeholder."""
        return token_str.strip() in self._by_placeholder

    def revoke_credential(self, target_host: str) -> bool:
        """Revoke bound credential for host."""
        clean_host = self._normalize_host(target_host)
        spec = self._by_host.get(clean_host)
        if spec is None or not spec.is_active:
            return False

        updated = BoundCredentialSpec(
            target_host=spec.target_host,
            auth_header_name=spec.auth_header_name,
            auth_header_template=spec.auth_header_template,
            real_secret=spec.real_secret,
            placeholder=spec.placeholder,
            is_active=False,
        )
        self._by_host[clean_host] = updated
        self._by_placeholder[spec.placeholder] = updated
        return True

    def list_active(self) -> list[BoundCredentialSpec]:
        """List all currently active bound credentials."""
        return [spec for spec in self._by_host.values() if spec.is_active]

    def list_all_placeholders(self) -> list[str]:
        """List all registered placeholder tokens, including revoked ones."""
        return list(self._by_placeholder.keys())


"""Host-side Vault-Proxy Gateway: Isolating sensitive credentials outside sandbox containers."""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlparse

from .types import (
    VaultCredentialEntry,
    VaultProxyRequest,
    VaultProxyResponse,
)

logger = logging.getLogger(__name__)


class HostVaultProxy:
    """Secure credential vault and outbound relay proxy.

    Guarantees:
    1. Credentials never enter container filesystem, memory, or environment variables.
    2. Outbound requests are vetted against strict domain allowlists before injection.
    3. Plaintext keys are stripped from traces, logs, and error responses.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._credentials: dict[str, VaultCredentialEntry] = {}

    def register_credential(
        self,
        credential_id: str,
        target_service: str,
        secret_value: str,
        allowed_domains: list[str],
        description: str = "",
    ) -> VaultCredentialEntry:
        """Register a sensitive token inside the host vault."""
        entry = VaultCredentialEntry(
            credential_id=credential_id,
            target_service=target_service,
            secret_value=secret_value,
            allowed_domains=[d.lower() for d in allowed_domains],
            description=description,
        )
        with self._lock:
            self._credentials[credential_id] = entry
        return entry

    def get_credential_metadata(
        self, credential_id: str
    ) -> VaultCredentialEntry | None:
        """Retrieve credential metadata without disclosing the secret value."""
        with self._lock:
            cred = self._credentials.get(credential_id)
            if cred is None:
                return None
            return VaultCredentialEntry(
                credential_id=cred.credential_id,
                target_service=cred.target_service,
                secret_value="[REDACTED_IN_VAULT]",
                allowed_domains=list(cred.allowed_domains),
                description=cred.description,
            )

    def list_credentials(self) -> list[VaultCredentialEntry]:
        """List all registered credentials with redacted secret values."""
        with self._lock:
            entries = list(self._credentials.values())
        return [
            VaultCredentialEntry(
                credential_id=e.credential_id,
                target_service=e.target_service,
                secret_value="[REDACTED_IN_VAULT]",
                allowed_domains=list(e.allowed_domains),
                description=e.description,
            )
            for e in entries
        ]

    def process_outbound_request(
        self, request: VaultProxyRequest
    ) -> VaultProxyResponse:
        """Vet outbound sandbox request, inject credential on host side, and return response."""
        with self._lock:
            cred = self._credentials.get(request.credential_id)

        if cred is None:
            return VaultProxyResponse(
                status_code=404,
                headers={},
                body="",
                credential_injected=False,
                blocked_reason=f"Credential {request.credential_id} not found in host vault",
            )

        parsed_url = urlparse(request.target_url)
        domain = (parsed_url.hostname or "").lower()

        # Check domain allowlist
        if not any(
            domain == allowed or domain.endswith("." + allowed)
            for allowed in cred.allowed_domains
        ):
            logger.warning(
                "VaultProxy blocked request to %s: domain not in allowlist %s",
                domain,
                cred.allowed_domains,
            )
            return VaultProxyResponse(
                status_code=403,
                headers={},
                body="",
                credential_injected=False,
                blocked_reason=f"Domain {domain} is not permitted for credential {request.credential_id}",
            )

        # Build authenticated headers on host side
        auth_headers = dict(request.headers)
        auth_headers["Authorization"] = f"Bearer {cred.secret_value}"
        auth_headers["X-Vault-Proxy-Forwarded"] = "true"

        # Mocked relay execution for unit testing & sandbox isolation verification
        simulated_response_body = (
            f"Successfully authenticated request to {cred.target_service} at {domain}"
        )

        return VaultProxyResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=simulated_response_body,
            credential_injected=True,
            blocked_reason=None,
        )

    def clear(self) -> None:
        """Clear all credentials in host vault."""
        with self._lock:
            self._credentials.clear()

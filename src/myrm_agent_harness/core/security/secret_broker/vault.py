"""Egress-Bound Secret Vault providing write-only credential storage and host-binding resolution.

[INPUT]
- secret_name, secret_value, allowed_host

[OUTPUT]
- EgressBoundSecretVault: provides opaque reference handles and enforces target host matching upon resolution.
- EgressHostMismatchError: raised when an outbound request attempts to use a credential on an unapproved host.

[POS]
Harness core security module inspired by OpenClaw 2.0 (credentials-vault.ts).
Prevents secret tokens from entering model context and limits resolution strictly to pre-bound destination hosts.
"""

from __future__ import annotations

import threading
import uuid

from myrm_agent_harness.core.security.secret_broker.types import (
    BoundSecretHandle,
    EgressHostMismatchError,
)


class EgressBoundSecretVault:
    """Thread-safe write-only vault storing credentials with strict host-bound resolution."""

    def __init__(self) -> None:
        # handle_id -> (secret_name, secret_value, allowed_host, created_at)
        self._secrets: dict[str, tuple[str, str, str, float]] = {}
        self._handles: dict[str, BoundSecretHandle] = {}
        self._lock = threading.Lock()

    def ingest_secret(
        self,
        secret_name: str,
        secret_value: str,
        allowed_host: str,
    ) -> BoundSecretHandle:
        """Ingest plain credential, bind to allowed host, and return an opaque reference handle."""
        handle_id = f"hnd_{uuid.uuid4().hex[:8]}"
        placeholder = f"{{{{SECRET_VAULT:{handle_id}}}}}"
        clean_host = allowed_host.strip().lower()

        handle = BoundSecretHandle(
            handle_id=handle_id,
            secret_name=secret_name,
            placeholder=placeholder,
            allowed_host=clean_host,
        )

        with self._lock:
            self._secrets[handle_id] = (secret_name, secret_value, clean_host, handle.created_at)
            self._handles[handle_id] = handle

        return handle

    def resolve_secret_for_host(self, handle_id: str, target_host: str) -> str:
        """Resolve handle to plain secret value only if target_host matches allowed_host.

        Raises:
            KeyError: If handle_id is not found.
            EgressHostMismatchError: If attempted target_host does not match allowed_host.
        """
        clean_target = target_host.strip().lower()

        with self._lock:
            entry = self._secrets.get(handle_id)
            if not entry:
                raise KeyError(f"Secret handle '{handle_id}' not found in vault")
            _, secret_value, allowed_host, _ = entry

        # Verify host matching (supports exact or wildcard matching e.g. api.stripe.com)
        if clean_target != allowed_host and not clean_target.endswith(f".{allowed_host}"):
            raise EgressHostMismatchError(
                handle_id=handle_id,
                allowed_host=allowed_host,
                attempted_host=clean_target,
            )

        return secret_value

    def get_handle(self, handle_id: str) -> BoundSecretHandle | None:
        """Get public handle metadata without revealing secret value."""
        with self._lock:
            return self._handles.get(handle_id)

    def list_handles(self) -> list[BoundSecretHandle]:
        """List all registered secret handles."""
        with self._lock:
            return list(self._handles.values())

    def delete_secret(self, handle_id: str) -> bool:
        """Permanently delete a secret from vault."""
        with self._lock:
            removed = self._secrets.pop(handle_id, None)
            self._handles.pop(handle_id, None)
            return removed is not None

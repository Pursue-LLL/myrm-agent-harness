"""On-demand credential resolver.

[INPUT]
- Lazy credential provider callbacks registered per handle.

[OUTPUT]
- OnDemandCredentialResolver: Resolves requested credentials, verifies collision safety, and returns MultiEncodingSecretMasker.

[POS]
Credential materialization engine implementing zero-disk lazy binding and conflict detection.
"""

from __future__ import annotations

from collections.abc import Callable

from myrm_agent_harness.core.security.on_demand_masking.masker import (
    MultiEncodingSecretMasker,
)
from myrm_agent_harness.core.security.on_demand_masking.types import (
    CredentialField,
    MaterializedCredential,
)


class CredentialConflictError(ValueError):
    """Raised when two requested credentials attempt to set differing values for the same key."""


class OnDemandCredentialResolver:
    """Resolves and materializes requested credentials on demand with conflict detection."""

    def __init__(self) -> None:
        self._registry: dict[str, Callable[[], list[CredentialField]]] = {}

    def register_provider(
        self, handle: str, provider: Callable[[], list[CredentialField]]
    ) -> None:
        """Register a lazy credential provider."""
        self._registry[handle] = provider

    def resolve_requested(
        self, requested_handles: list[str]
    ) -> tuple[dict[str, str], MultiEncodingSecretMasker]:
        """Resolve only the explicitly requested credentials.

        Returns:
            Tuple of (execution_env, multi_encoding_masker)
        Raises:
            CredentialConflictError if conflicting values are supplied for any key.
        """
        command_env: dict[str, str] = {}
        secrets_to_mask: dict[str, str] = {}

        unique_handles = list(dict.fromkeys(requested_handles))
        for handle in unique_handles:
            if handle not in self._registry:
                continue

            fields = self._registry[handle]()
            for field in fields:
                if field.key in command_env and command_env[field.key] != field.value:
                    raise CredentialConflictError(
                        f"requested credentials provide conflicting environment key: {field.key}"
                    )
                command_env[field.key] = field.value
                if field.is_secret:
                    secrets_to_mask[field.key] = field.value

        masker = MultiEncodingSecretMasker(secrets_to_mask)
        return command_env, masker

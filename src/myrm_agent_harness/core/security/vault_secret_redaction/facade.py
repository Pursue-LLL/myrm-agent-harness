"""Facade entry point for always-on vault secret dynamic redaction.

[INPUT]
- Text, tool returns, inbound user messages, credential vaults, and stream chunks.

[OUTPUT]
- Unified interface for dynamic secret sanitization, vault synchronization, and stream scrubbing.

[POS]
- Harness core security primitive in core/security/vault_secret_redaction/facade.py.
"""

from __future__ import annotations

from collections.abc import Mapping

from myrm_agent_harness.core.security.credential_vault import CredentialVault

from .pipeline import AlwaysOnVaultSecretRedactor
from .stream_scrubber import SecretStreamScrubber
from .types import (
    RedactionResult,
    SecretSourceType,
    VaultSecretRedactionConfig,
)


class VaultSecretRedactionFacade:
    """High-level facade providing always-on dynamic vault secret redaction."""

    def __init__(
        self, config: VaultSecretRedactionConfig | None = None
    ) -> None:
        self._redactor = AlwaysOnVaultSecretRedactor(config=config)

    @property
    def redactor(self) -> AlwaysOnVaultSecretRedactor:
        """Underlying redactor engine instance."""
        return self._redactor

    def get_config(self) -> VaultSecretRedactionConfig:
        """Get current redaction configuration."""
        return self._redactor.config

    def update_config(self, config: VaultSecretRedactionConfig) -> None:
        """Update redaction configuration."""
        self._redactor.update_config(config)

    def register_secret(
        self,
        name: str,
        value: str,
        source: SecretSourceType = SecretSourceType.DYNAMIC_CAPTURED,
        mask: str | None = None,
    ) -> bool:
        """Register a secret value into the active redaction set."""
        return self._redactor.register_secret(
            name=name, value=value, source=source, mask=mask
        )

    def unregister_secret(self, name: str) -> bool:
        """Unregister a secret from the active redaction set."""
        return self._redactor.unregister_secret(name)

    def list_secret_names(self) -> list[str]:
        """List all active secret names."""
        return self._redactor.list_secret_names()

    def sync_from_credential_vault(self, vault: CredentialVault) -> int:
        """Sync secrets dynamically from a CredentialVault instance."""
        return self._redactor.sync_from_credential_vault(vault)

    def collect_ambient_env_secrets(
        self, env_dict: Mapping[str, str] | None = None
    ) -> int:
        """Collect ambient credentials from environment variables."""
        return self._redactor.collect_ambient_env_secrets(env_dict)

    def redact_text(self, text: str) -> RedactionResult:
        """Redact registered secrets from a raw string."""
        return self._redactor.redact_text(text)

    def redact_tool_return(
        self, content: object
    ) -> tuple[object, RedactionResult]:
        """Redact secrets from tool execution output."""
        return self._redactor.redact_tool_return(content)

    def redact_user_message(
        self, content: object
    ) -> tuple[object, RedactionResult]:
        """Redact secrets from inbound user message payloads."""
        return self._redactor.redact_user_message(content)

    def create_stream_scrubber(self) -> SecretStreamScrubber:
        """Create a sliding-window stream scrubber for chunk outputs."""
        return self._redactor.create_stream_scrubber()

    def get_stats(self) -> dict[str, int]:
        """Get match statistics for all registered secrets."""
        return self._redactor.get_stats()

    def clear(self) -> None:
        """Clear all registered secrets and stats."""
        self._redactor.clear()


_global_facade: VaultSecretRedactionFacade | None = None


def get_vault_secret_redaction_facade() -> VaultSecretRedactionFacade:
    """Return process-wide singleton facade instance."""
    global _global_facade
    if _global_facade is None:
        _global_facade = VaultSecretRedactionFacade()
    return _global_facade

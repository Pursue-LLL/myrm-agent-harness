"""Directory trust gate for preventing credential exfiltration in untrusted repos.

[INPUT]
- myrm_agent_harness.core.security.dir_trust_gate.trust_store::DirectoryTrustStore (POS: Persistent store for trusted directories)
- myrm_agent_harness.core.security.dir_trust_gate.types::ProjectRemoteConfig (POS: Remote repository configuration descriptor)

[OUTPUT]
- DirTrustGate: Evaluates and gates remote credentials against directory authorization.

[POS]
Security gate enforcing directory trust boundaries to prevent credential exfiltration.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.core.security.dir_trust_gate.trust_store import (
    DirectoryTrustStore,
)
from myrm_agent_harness.core.security.dir_trust_gate.types import (
    GatedRemoteConfig,
    ProjectRemoteConfig,
)


class DirTrustGate:
    """Enforces directory trust boundaries on repository remote settings."""

    def __init__(self, trust_store: DirectoryTrustStore | None = None) -> None:
        """Initialize the trust gate.

        Args:
            trust_store: Directory trust store backend. If None, default store is created.
        """
        self._trust_store = trust_store or DirectoryTrustStore()

    @property
    def trust_store(self) -> DirectoryTrustStore:
        """Get the underlying trust store."""
        return self._trust_store

    def evaluate(
        self,
        directory: str | Path,
        config: ProjectRemoteConfig,
    ) -> GatedRemoteConfig:
        """Evaluate repository configuration against directory trust state.

        If the directory is trusted:
            Allows remote_url and remote_token.
        If the directory is untrusted:
            Drops remote_url and remote_token, sets is_remote_allowed=False,
            emits a security warning, but preserves benign non-credential fields like scope.

        Args:
            directory: Directory path of the workspace / cloned repo.
            config: Extracted project configuration.

        Returns:
            GatedRemoteConfig with sanitized remote configuration and warning.
        """
        canonical_dir = DirectoryTrustStore.normalize_directory(directory)
        is_trusted = self._trust_store.is_trusted(canonical_dir)

        has_remote_credentials = bool(config.remote_url or config.remote_token)

        if is_trusted:
            return GatedRemoteConfig(
                sanitized_directory=canonical_dir,
                is_trusted=True,
                is_remote_allowed=True,
                allowed_remote_url=config.remote_url,
                allowed_remote_token=config.remote_token,
                effective_scope=config.scope,
                warning_message=None,
            )

        # Untrusted directory
        warning: str | None = None
        if has_remote_credentials:
            warning = (
                f"Directory '{canonical_dir}' is untrusted. Remote settings (URL/token) "
                f"were dropped to prevent credential exfiltration. "
                f"Please authorize this workspace in the security settings or trust dialog."
            )

        return GatedRemoteConfig(
            sanitized_directory=canonical_dir,
            is_trusted=False,
            is_remote_allowed=False,
            allowed_remote_url=None,
            allowed_remote_token=None,
            effective_scope=config.scope,
            warning_message=warning,
        )

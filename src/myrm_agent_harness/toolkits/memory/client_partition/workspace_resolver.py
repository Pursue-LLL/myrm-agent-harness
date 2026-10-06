"""Client workspace path resolution and containment boundary enforcement.

[INPUT]
- pathlib::{Path}
- re
- myrm_agent_harness.toolkits.memory.client_partition.types::{ClientPartitionConfig, ClientWorkspaceDescriptor}

[OUTPUT]
- ClientWorkspaceResolver: Deterministic resolver for isolated client workspace folders

[POS]
Safe directory derivation and traversal prevention for client-isolated workspace partitions.
"""

from __future__ import annotations

import re
from pathlib import Path

from myrm_agent_harness.toolkits.memory.client_partition.types import (
    ClientPartitionConfig,
    ClientWorkspaceDescriptor,
)

_CLIENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


class ClientWorkspaceResolver:
    """Derives and validates isolated workspace directories for clients."""

    def __init__(self, base_dir: Path | str) -> None:
        self._base_dir = Path(base_dir).resolve()

    @property
    def base_dir(self) -> Path:
        """Root directory under which client workspaces are mounted."""
        return self._base_dir

    def validate_client_id(self, client_id: str) -> str:
        """Ensure client_id is a secure, canonical slug without path separators."""
        cleaned = client_id.strip()
        if not cleaned:
            raise ValueError("Client identifier cannot be empty")
        if not _CLIENT_ID_RE.fullmatch(cleaned):
            raise ValueError(
                f"Invalid client identifier {cleaned!r}. "
                "Must be 1-64 alphanumeric characters, underscores, hyphens, or dots."
            )
        if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
            raise ValueError(f"Client identifier {cleaned!r} contains forbidden path components")
        return cleaned

    def resolve_workspace(
        self,
        config: ClientPartitionConfig,
        *,
        auto_create: bool = False,
    ) -> ClientWorkspaceDescriptor:
        """Derive an isolated workspace directory from partition configuration.

        Ensures that the resolved absolute path is strictly contained within
        the configured base root, preventing any path traversal vulnerabilities.
        """
        valid_client_id = self.validate_client_id(config.client_id)
        relative_path = Path(config.workspace_root) / valid_client_id
        target_path = (self._base_dir / relative_path).resolve()

        # Strict sandbox boundary containment assertion
        if not target_path.is_relative_to(self._base_dir):
            raise ValueError(
                f"Resolved workspace {target_path} escapes sandbox base directory {self._base_dir}"
            )

        if auto_create:
            target_path.mkdir(parents=True, exist_ok=True)

        return ClientWorkspaceDescriptor(
            client_id=valid_client_id,
            relative_path=str(relative_path),
            absolute_path=str(target_path),
            is_isolated=True,
        )

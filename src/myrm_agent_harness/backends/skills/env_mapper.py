"""Environment variable mapper for credential files.

Maps credential file paths to environment variables, enabling skills to
declare `credential_env_mapping: {"GOOGLE_TOKEN_PATH": "google_token.json"}`
and have the framework automatically set those environment variables.

[INPUT]
- types::SkillMetadata (POS: credential_env_mapping field)
- pathlib::Path (stdlib: path operations)

[OUTPUT]
- CredentialEnvMapper: applies environment variable mappings with security checks

[POS]
Lightweight mapper for developer experience. Enables skills to work without
requiring users to manually configure environment variables.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class CredentialEnvMapper:
    """Maps credential files to environment variables with workspace boundary checks."""

    def __init__(self, workspace_root: Path) -> None:
        """Initialize mapper.

        Args:
            workspace_root: Absolute path to workspace root
        """
        self._workspace_root = workspace_root.resolve()

    def apply_env_mapping(
        self,
        mapping: dict[str, str],
        existing_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Apply credential environment variable mappings.

        Args:
            mapping: Environment variable mappings {"VAR_NAME": "relative/path"}
            existing_env: Optional existing env dict to update (defaults to os.environ)

        Returns:
            Dictionary of environment variables to set

        Raises:
            ValueError: If any path is invalid (absolute or traverses workspace)
        """
        env_vars: dict[str, str] = {}
        invalid_mappings: list[str] = []

        for env_name, rel_path in mapping.items():
            if not self._is_valid_env_name(env_name):
                logger.warning("Skipping invalid environment variable name: %s", env_name)
                continue

            # Reject absolute paths
            if os.path.isabs(rel_path):
                invalid_mappings.append(f"{env_name}={rel_path} (absolute path not allowed)")
                continue

            # Resolve and check workspace boundary
            try:
                resolved = (self._workspace_root / rel_path).resolve()
                resolved.relative_to(self._workspace_root)
            except ValueError:
                invalid_mappings.append(f"{env_name}={rel_path} (path traversal detected)")
                logger.warning(
                    "Credential env mapping rejected: %s=%s (resolves outside workspace)",
                    env_name,
                    rel_path,
                )
                continue
            except (OSError, RuntimeError) as e:
                invalid_mappings.append(f"{env_name}={rel_path} (resolution failed: {e})")
                continue

            # Store absolute path (resolved within workspace)
            env_vars[env_name] = str(resolved)

        # Log warnings for invalid mappings
        if invalid_mappings:
            logger.warning(
                "Skipped %d invalid credential env mappings:\n%s",
                len(invalid_mappings),
                "\n".join(f"  - {m}" for m in invalid_mappings),
            )

        # Apply to environment if requested
        if existing_env is not None:
            existing_env.update(env_vars)

        return env_vars

    @staticmethod
    def _is_valid_env_name(name: str) -> bool:
        """Check if environment variable name is valid.

        Valid names:
        - Start with letter or underscore
        - Contain only letters, digits, underscores
        - Uppercase convention (not enforced but recommended)

        Args:
            name: Environment variable name

        Returns:
            True if valid
        """
        if not name:
            return False

        # Must start with letter or underscore
        if not (name[0].isalpha() or name[0] == "_"):
            return False

        # Must contain only alphanumerics and underscores
        return all(c.isalnum() or c == "_" for c in name)

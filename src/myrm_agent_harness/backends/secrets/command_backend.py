"""Command Secret Provider Implementation.

Resolves agent secrets dynamically via external helper command (Zero-Disk Plaintext).

[INPUT]
- .protocols::AgentSecretBackend (POS: Protocol for Agent Secret Storage Backend)

[OUTPUT]
- CommandSecretBackend: Dynamic command-based secret resolver
- CommandExecutionError: Raised when secret command execution fails

[POS]
Harness backends/secrets/ layer. Resolves secrets on demand using an external helper CLI
(e.g., pass, secret-tool, keepassxc-cli, 1Password op CLI, Bitwarden bw).
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from .protocols import AgentSecretBackend

logger = logging.getLogger(__name__)


class CommandExecutionError(Exception):
    """Raised when an external secret command helper fails or times out."""

    pass


class CommandSecretBackend(AgentSecretBackend):
    """Dynamically resolves secrets for agents using an external shell command helper.

    Follows Zero-Disk architecture: secrets are never persisted in plaintext on disk,
    but retrieved on demand from user-configured local vaults or command helpers.
    """

    def __init__(
        self,
        command_template: list[str] | str,
        timeout_seconds: float = 5.0,
        env_passthrough: bool = True,
    ) -> None:
        """Initialize CommandSecretBackend.

        Args:
            command_template: The command to execute. If a list, e.g. ["pass", "show"],
                              the key name is appended or injected.
                              If a string, $MYRM_SECRET_KEY is substituted.
            timeout_seconds: Max execution time before fail-safe abort (default 5.0s).
            env_passthrough: Whether to pass filtered environment variables.
        """
        self.command_template = command_template
        self.timeout_seconds = timeout_seconds
        self.env_passthrough = env_passthrough

    def _execute_command(self, key_name: str) -> str | None:
        """Execute helper command with fail-safe bounds."""
        env = os.environ.copy() if self.env_passthrough else {}
        env["MYRM_SECRET_KEY"] = key_name

        if isinstance(self.command_template, list):
            has_placeholder = any("$MYRM_SECRET_KEY" in part for part in self.command_template)
            if has_placeholder:
                cmd = [part.replace("$MYRM_SECRET_KEY", key_name) for part in self.command_template]
            else:
                cmd = list(self.command_template) + [key_name]
            use_shell = False
        else:
            cmd = self.command_template.replace("$MYRM_SECRET_KEY", key_name)
            use_shell = True

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=use_shell,
                env=env,
                check=False,
            )
            if proc.returncode != 0:
                logger.warning(
                    "Command secret helper returned non-zero (%d) for key %s: %s",
                    proc.returncode,
                    key_name,
                    proc.stderr.strip()[:200],
                )
                return None
            return proc.stdout.strip() or None
        except subprocess.TimeoutExpired as exc:
            logger.error("Command secret helper timed out (%.1fs) for key %s", self.timeout_seconds, key_name)
            raise CommandExecutionError(f"Secret command timed out for key '{key_name}'") from exc
        except Exception as exc:
            logger.error("Failed to run command secret helper for key %s: %s", key_name, exc)
            raise CommandExecutionError(f"Secret command failed: {exc}") from exc

    def set_secret(self, agent_id: str, key_name: str, secret_value: str) -> None:
        """Command backend is read-only for external vaults."""
        raise NotImplementedError("CommandSecretBackend is read-only. Manage secrets in your external vault.")

    def get_secret(self, agent_id: str, key_name: str) -> str | None:
        """Retrieve a secret dynamically via the external command helper."""
        return self._execute_command(key_name)

    def delete_secret(self, agent_id: str, key_name: str) -> bool:
        """Command backend is read-only."""
        raise NotImplementedError("CommandSecretBackend is read-only.")

    def get_all_secrets(self, agent_id: str) -> dict[str, str]:
        """Bulk resolution is not supported unless keys are explicitly known."""
        return {}

    def delete_all_secrets(self, agent_id: str) -> None:
        """Command backend is read-only."""
        raise NotImplementedError("CommandSecretBackend is read-only.")

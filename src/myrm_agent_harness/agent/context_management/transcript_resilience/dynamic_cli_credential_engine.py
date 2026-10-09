# [INPUT]: DynamicCredentialSpec from resilience_types
# [OUTPUT]: DynamicCliCredentialEngine
# [POS]: myrm_agent_harness.agent.context_management.transcript_resilience.dynamic_cli_credential_engine
"""External CLI Vault & Dynamic Scripted Credential Engine (Item 333).

Executes secure isolated external CLI commands (e.g. pass, keepassxc-cli, secret-tool)
to dynamically evaluate API keys and secrets in-memory without persistent plaintext disk storage.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Final

from myrm_agent_harness.agent.context_management.transcript_resilience.resilience_types import (
    DynamicCredentialSpec,
)


class DynamicCliCredentialEngine:
    """Thread-safe engine resolving API credentials dynamically from external CLI vaults."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # spec_fingerprint -> (cached_value: str, expires_at_monotonic: float)
        self._cache: dict[str, tuple[str, float]] = {}

    def resolve_credential(
        self,
        spec: DynamicCredentialSpec,
        force_refresh: bool = False,
    ) -> str:
        """Dynamically evaluate credential from external command, checking cache first.

        Args:
            spec: Command arguments and execution parameters.
            force_refresh: If True, bypass cache and re-evaluate immediately.

        Returns:
            Resolved plaintext secret token in memory.

        Raises:
            ValueError: If command_args is empty.
            subprocess.TimeoutExpired: If command execution times out.
            RuntimeError: If command exits with non-zero status.
        """
        if not spec.command_args:
            raise ValueError("DynamicCredentialSpec command_args cannot be empty.")

        fingerprint = "::".join(spec.command_args)
        now = time.monotonic()

        with self._lock:
            if not force_refresh and fingerprint in self._cache:
                cached_val, expires_at = self._cache[fingerprint]
                if now < expires_at:
                    return cached_val

        # Prepare environment
        sub_env = dict(os.environ)
        if spec.env_vars:
            sub_env.update(spec.env_vars)

        try:
            # Execute in safe isolated subprocess without shell=True
            proc = subprocess.run(
                spec.command_args,
                env=sub_env,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(
                f"CLI vault command {spec.command_args} timed out after {spec.timeout_seconds}s"
            ) from e

        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or f"process returned code {proc.returncode}"
            raise RuntimeError(
                f"CLI vault command {spec.command_args} failed: {err_msg}"
            )

        raw_out = proc.stdout.strip()
        token = self._parse_token_output(raw_out)

        with self._lock:
            expires_at = time.monotonic() + spec.cache_ttl_seconds
            self._cache[fingerprint] = (token, expires_at)

        return token

    def _parse_token_output(self, raw: str) -> str:
        """Parse raw CLI output to extract either pure token or KEY=VALUE format."""
        if not raw:
            return ""

        # If multi-line, inspect lines
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            return ""

        first_line = lines[0]
        # Check if formatted as KEY=VALUE
        if "=" in first_line:
            parts = first_line.split("=", 1)
            return parts[1].strip()

        # Otherwise treat first line as token itself
        return first_line

    def clear_cache(self) -> None:
        """Purge all in-memory cached secrets."""
        with self._lock:
            self._cache.clear()

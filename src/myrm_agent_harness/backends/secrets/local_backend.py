"""Local Secret Backend Implementation.

This backend provides out-of-the-box persistent storage for agent secrets
using the local file system and AES-256-GCM encryption.

[INPUT]
- utils.crypto.config_crypto::ConfigCrypto (POS: Pure encryption tool. No business logic (no deploy_mode, no user_id). All methods are static (no state). Key injection via parameter. Design principles: No business logic (no deploy_mode, no user_id) No environment variables (key injected via parameter) Stateless (all methods are static) Pure functions (same input → same output))
- utils.crypto.exceptions::DecryptionError, (POS: Config crypto exceptions.)

[OUTPUT]
- SecretEncryptionError: Raised when secret encryption or decryption fails.
- LocalSecretBackend: Store agent secrets in an encrypted .secrets.enc file wit...

[POS]
Local Secret Backend Implementation.
"""

import contextlib
import os
import tempfile
from pathlib import Path

from myrm_agent_harness.utils.crypto.config_crypto import ConfigCrypto
from myrm_agent_harness.utils.crypto.exceptions import DecryptionError, EncryptionError

from .protocols import AgentSecretBackend


class SecretEncryptionError(Exception):
    """Raised when secret encryption or decryption fails."""

    pass


class LocalSecretBackend(AgentSecretBackend):
    """Store agent secrets in an encrypted .secrets.enc file within the agent's bundle directory.

    This is the default persistent backend for the framework.
    """

    def __init__(self, master_key: str | bytes, base_dir: str | None = None):
        """Initialize the Local Secret Backend.

        Args:
            master_key: The secret string or bytes used to derive the 256-bit encryption key.
                        Must be explicitly provided by the caller.
            base_dir: The base directory for agent bundles (defaults to ~/.myrm/agents).
        """
        if not master_key:
            raise ValueError("master_key must be explicitly provided to initialize LocalSecretBackend.")

        self._encryption_key = ConfigCrypto.derive_key(master_key)

        myrm_dir = Path(os.getenv("MYRM_DATA_DIR", str(Path.home() / ".myrm")))
        if base_dir is None:
            base_dir = str(myrm_dir / "agents")

        self.base_dir = base_dir

    def _get_secrets_path(self, agent_id: str) -> str:
        """Get the path to the agent's encrypted secrets file."""
        return os.path.join(self.base_dir, agent_id, ".secrets.enc")

    def _read_all_secrets(self, agent_id: str) -> dict[str, str]:
        """Read and decrypt all secrets from the file."""
        file_path = self._get_secrets_path(agent_id)
        if not os.path.exists(file_path):
            return {}

        try:
            with open(file_path, encoding="ascii") as f:
                ciphertext = f.read().strip()

            if not ciphertext:
                return {}

            decrypted: dict[str, object] = ConfigCrypto.decrypt_value(ciphertext, self._encryption_key)
            # Ensure all values are strings as required by env vars
            return {k: str(v) for k, v in decrypted.items()}
        except DecryptionError as e:
            raise SecretEncryptionError(f"Failed to decrypt secrets for agent {agent_id}: {e}") from e
        except Exception:
            # Fallback for OS or IO errors
            return {}

    def _write_all_secrets(self, agent_id: str, secrets: dict[str, str]) -> None:
        """Encrypt and write all secrets to the file."""
        bundle_dir = os.path.join(self.base_dir, agent_id)
        os.makedirs(bundle_dir, exist_ok=True)

        file_path = self._get_secrets_path(agent_id)

        if not secrets:
            if os.path.exists(file_path):
                os.remove(file_path)
            return

        try:
            ciphertext = ConfigCrypto.encrypt_value(secrets, self._encryption_key)  # type: ignore[arg-type]

            # Atomic write: temp file + os.replace to prevent data corruption on crash
            fd, tmp_path = tempfile.mkstemp(dir=bundle_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="ascii") as f:
                    f.write(ciphertext)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, file_path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
        except EncryptionError as e:
            raise SecretEncryptionError(f"Failed to encrypt secrets for agent {agent_id}: {e}") from e

    def set_secret(self, agent_id: str, key_name: str, secret_value: str) -> None:
        """Store or update a secret for an agent."""
        secrets = self._read_all_secrets(agent_id)
        secrets[key_name] = secret_value
        self._write_all_secrets(agent_id, secrets)

    def get_secret(self, agent_id: str, key_name: str) -> str | None:
        """Retrieve a decrypted secret for an agent."""
        secrets = self._read_all_secrets(agent_id)
        return secrets.get(key_name)

    def delete_secret(self, agent_id: str, key_name: str) -> bool:
        """Delete a specific secret for an agent."""
        secrets = self._read_all_secrets(agent_id)
        if key_name in secrets:
            del secrets[key_name]
            self._write_all_secrets(agent_id, secrets)
            return True
        return False

    def get_all_secrets(self, agent_id: str) -> dict[str, str]:
        """Retrieve all decrypted secrets for an agent."""
        return self._read_all_secrets(agent_id)

    def delete_all_secrets(self, agent_id: str) -> None:
        """Delete all secrets associated with an agent."""
        file_path = self._get_secrets_path(agent_id)
        if os.path.exists(file_path):
            os.remove(file_path)

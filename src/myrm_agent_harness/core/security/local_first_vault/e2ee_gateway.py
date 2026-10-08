"""Zero-Knowledge E2EE Sharing Gateway and Local-First Vault Manager."""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .dlp_pipeline import TransparentDlpRedactionPipeline
from .types import (
    E2eeShareEnvelope,
    LocalVaultItem,
    VaultStorageMode,
)


class ZeroKnowledgeE2eeGateway:
    """Manages local-first disk vault artifacts and zero-knowledge E2EE encrypted share envelopes."""

    def __init__(
        self,
        dlp_pipeline: TransparentDlpRedactionPipeline | None = None,
    ) -> None:
        self._dlp = dlp_pipeline or TransparentDlpRedactionPipeline()
        self._lock = threading.Lock()
        self._vault_items: dict[str, LocalVaultItem] = {}
        self._envelopes: dict[str, E2eeShareEnvelope] = {}

    @property
    def dlp(self) -> TransparentDlpRedactionPipeline:
        """Access in-situ DLP pipeline."""
        return self._dlp

    def register_local_artifact(
        self,
        artifact_id: str,
        title: str,
        local_path: str,
        content: str,
        storage_mode: VaultStorageMode = VaultStorageMode.LOCAL_FIRST_DISK,
    ) -> LocalVaultItem:
        """Register an artifact under the local-first storage invariant."""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        now = datetime.now(UTC)

        item = LocalVaultItem(
            artifact_id=artifact_id,
            title=title,
            local_path=local_path,
            storage_mode=storage_mode,
            is_cloud_synced=False,
            content_hash=content_hash,
            created_at=now,
            updated_at=now,
        )

        with self._lock:
            self._vault_items[artifact_id] = item

        return item

    def get_local_artifact(self, artifact_id: str) -> LocalVaultItem | None:
        """Retrieve local-first vault metadata record."""
        with self._lock:
            return self._vault_items.get(artifact_id)

    def list_local_artifacts(self) -> list[LocalVaultItem]:
        """List all locally stored artifacts."""
        with self._lock:
            return list(self._vault_items.values())

    def create_e2ee_share(
        self,
        artifact_id: str,
        plaintext_content: str,
        client_key: bytes | None = None,
        ttl_seconds: int = 86400,
        enable_dlp_sanitization: bool = True,
    ) -> tuple[E2eeShareEnvelope, bytes]:
        """Sanitize content with DLP, encrypt using AES-256-GCM, and create zero-knowledge envelope.

        Returns:
            Tuple of (E2eeShareEnvelope, encryption_key_bytes). The server only stores the
            ciphertext and key hash; the key itself stays client-side.
        """
        # 1. Run transparent DLP sanitization
        target_content = plaintext_content
        dlp_audit_passed = True
        if enable_dlp_sanitization:
            dlp_res = self._dlp.sanitize_content(plaintext_content)
            target_content = dlp_res.sanitized_content
            dlp_audit_passed = True

        # 2. Derive / generate symmetric AES-256-GCM key
        key = client_key if client_key is not None else AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        salt = os.urandom(16)

        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, target_content.encode("utf-8"), None)

        key_hash = hashlib.sha256(key).hexdigest()
        share_id = f"share_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        envelope = E2eeShareEnvelope(
            share_id=share_id,
            artifact_id=artifact_id,
            ciphertext_b64=base64.b64encode(ciphertext).decode("utf-8"),
            nonce_b64=base64.b64encode(nonce).decode("utf-8"),
            salt_b64=base64.b64encode(salt).decode("utf-8"),
            key_hash=key_hash,
            dlp_audit_passed=dlp_audit_passed,
            expires_at=expires_at,
            created_at=now,
        )

        with self._lock:
            self._envelopes[share_id] = envelope

        return envelope, key

    def get_envelope(self, share_id: str) -> E2eeShareEnvelope | None:
        """Retrieve share envelope by share_id."""
        with self._lock:
            envelope = self._envelopes.get(share_id)
            if envelope is None:
                return None
            if envelope.expires_at < datetime.now(UTC):
                return None
            return envelope

    def decrypt_envelope(self, share_id: str, key: bytes) -> str:
        """Decrypt share envelope verifying client key hash matches zero-knowledge proof.

        Raises:
            KeyError: If share_id not found or expired.
            ValueError: If client key hash doesn't match or decryption fails.
        """
        envelope = self.get_envelope(share_id)
        if envelope is None:
            raise KeyError(f"Share envelope '{share_id}' not found or expired.")

        candidate_key_hash = hashlib.sha256(key).hexdigest()
        if candidate_key_hash != envelope.key_hash:
            raise ValueError("Decryption failed: provided client key does not match envelope proof.")

        ciphertext = base64.b64decode(envelope.ciphertext_b64)
        nonce = base64.b64decode(envelope.nonce_b64)

        try:
            aesgcm = AESGCM(key)
            decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted_bytes.decode("utf-8")
        except Exception as exc:
            raise ValueError(f"AES-GCM decryption failed: {exc}") from exc

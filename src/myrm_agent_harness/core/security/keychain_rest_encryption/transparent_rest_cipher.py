"""
[POS] src/myrm_agent_harness/core/security/keychain_rest_encryption/transparent_rest_cipher.py
[INPUT] json, os, secrets, time, uuid, pathlib, cryptography.hazmat
[OUTPUT] TransparentRestCipher

High-performance AES-256-GCM cipher with HKDF-SHA256 domain-isolated key derivation
for transparent file and memory record rest encryption.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .types import CipherEnvelope, EncryptionDomain, TransparentRestMetrics


class TransparentRestCipher:
    """Provides transparent AES-256-GCM envelope encryption and decryption for rest assets."""

    def __init__(self) -> None:
        self._metrics: TransparentRestMetrics = TransparentRestMetrics()

    @property
    def metrics(self) -> TransparentRestMetrics:
        """Read-only access to cryptographic runtime metrics."""
        return self._metrics

    def derive_domain_key(
        self,
        master_key: bytes,
        domain: EncryptionDomain,
        salt: bytes,
    ) -> bytes:
        """Derive an isolated 256-bit AES key for a specific security domain using HKDF-SHA256."""
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=f"myrm.agent.rest.domain:{domain.value}".encode(),
        )
        self._metrics.domain_key_derivations += 1
        return hkdf.derive(master_key)

    def encrypt_bytes(
        self,
        data: bytes,
        domain: EncryptionDomain,
        master_key: bytes,
    ) -> CipherEnvelope:
        """Encrypt binary data into an AES-256-GCM CipherEnvelope."""
        salt: bytes = secrets.token_bytes(16)
        nonce: bytes = secrets.token_bytes(12)  # 96-bit standard nonce for AES-GCM
        domain_key: bytes = self.derive_domain_key(master_key, domain, salt)

        aesgcm = AESGCM(domain_key)
        # AESGCM.encrypt appends 16-byte authentication tag to the ciphertext
        encrypted_raw: bytes = aesgcm.encrypt(nonce, data, domain.value.encode())

        ciphertext: bytes = encrypted_raw[:-16]
        tag: bytes = encrypted_raw[-16:]

        digest = hashes.Hash(hashes.SHA256())
        digest.update(master_key)
        fingerprint = digest.finalize().hex()[:12]

        envelope = CipherEnvelope(
            envelope_id=f"env-{uuid.uuid4().hex[:12]}",
            domain=domain,
            salt_hex=salt.hex(),
            nonce_hex=nonce.hex(),
            tag_hex=tag.hex(),
            ciphertext_hex=ciphertext.hex(),
            key_fingerprint=fingerprint,
            created_at=time.time(),
        )

        self._metrics.encryptions_total += 1
        return envelope

    def decrypt_bytes(
        self,
        envelope: CipherEnvelope,
        master_key: bytes,
    ) -> bytes:
        """Decrypt a CipherEnvelope back into raw binary bytes."""
        try:
            salt: bytes = bytes.fromhex(envelope.salt_hex)
            nonce: bytes = bytes.fromhex(envelope.nonce_hex)
            tag: bytes = bytes.fromhex(envelope.tag_hex)
            ciphertext: bytes = bytes.fromhex(envelope.ciphertext_hex)

            domain_key: bytes = self.derive_domain_key(master_key, envelope.domain, salt)
            aesgcm = AESGCM(domain_key)

            # Recombine ciphertext and tag for verification and decryption
            combined = ciphertext + tag
            plaintext = aesgcm.decrypt(nonce, combined, envelope.domain.value.encode())

            self._metrics.decryptions_total += 1
            return plaintext
        except Exception as err:
            self._metrics.decryption_failures += 1
            raise ValueError(
                f"Failed to decrypt CipherEnvelope {envelope.envelope_id}: tag mismatch or invalid key"
            ) from err

    def encrypt_text(
        self,
        text: str,
        domain: EncryptionDomain,
        master_key: bytes,
    ) -> CipherEnvelope:
        """Encrypt UTF-8 string text into a CipherEnvelope."""
        return self.encrypt_bytes(text.encode("utf-8"), domain, master_key)

    def decrypt_text(
        self,
        envelope: CipherEnvelope,
        master_key: bytes,
    ) -> str:
        """Decrypt a CipherEnvelope and decode as UTF-8 string."""
        raw = self.decrypt_bytes(envelope, master_key)
        return raw.decode("utf-8")

    def encrypt_file(
        self,
        source_path: Path,
        dest_path: Path,
        domain: EncryptionDomain,
        master_key: bytes,
    ) -> CipherEnvelope:
        """Read a file, encrypt its content, and write the sealed envelope as JSON to dest_path."""
        content: bytes = source_path.read_bytes()
        envelope = self.encrypt_bytes(content, domain, master_key)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        envelope_dict: dict[str, str | float] = {
            "envelope_id": envelope.envelope_id,
            "domain": envelope.domain.value,
            "salt_hex": envelope.salt_hex,
            "nonce_hex": envelope.nonce_hex,
            "tag_hex": envelope.tag_hex,
            "ciphertext_hex": envelope.ciphertext_hex,
            "key_fingerprint": envelope.key_fingerprint,
            "created_at": envelope.created_at,
        }

        temp_dest = dest_path.with_suffix(dest_path.suffix + ".tmp")
        temp_dest.write_text(json.dumps(envelope_dict, indent=2), encoding="utf-8")
        os.replace(temp_dest, dest_path)

        self._metrics.files_encrypted_total += 1
        return envelope

    def decrypt_file(
        self,
        source_path: Path,
        dest_path: Path,
        master_key: bytes,
    ) -> bytes:
        """Read an encrypted envelope file, decrypt it, and write plaintext to dest_path."""
        raw_json = source_path.read_text(encoding="utf-8")
        data: dict[str, str | float] = json.loads(raw_json)

        envelope = CipherEnvelope(
            envelope_id=str(data["envelope_id"]),
            domain=EncryptionDomain(str(data["domain"])),
            salt_hex=str(data["salt_hex"]),
            nonce_hex=str(data["nonce_hex"]),
            tag_hex=str(data["tag_hex"]),
            ciphertext_hex=str(data["ciphertext_hex"]),
            key_fingerprint=str(data["key_fingerprint"]),
            created_at=float(data["created_at"]),
        )

        plaintext = self.decrypt_bytes(envelope, master_key)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        temp_dest = dest_path.with_suffix(dest_path.suffix + ".tmp")
        temp_dest.write_bytes(plaintext)
        os.replace(temp_dest, dest_path)

        self._metrics.files_decrypted_total += 1
        return plaintext

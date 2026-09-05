# INPUT: Raw secrets (API keys/tokens), text or streaming byte chunks, optional in-memory 256-bit AES key
# OUTPUT: Encrypted sentinel vouchers ("myrm-sent-v1.<base64url>.end"), resolved secrets, substituted streams
# POS: Harness core security egress layer. Zero external agent dependencies. Process-level ephemeral secret tokenization.

from __future__ import annotations

import base64
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

SENTINEL_PREFIX: str = "myrm-sent-v1."
SENTINEL_SUFFIX: str = ".end"
_SENTINEL_PATTERN: re.Pattern[str] = re.compile(r"myrm-sent-v1\.[A-Za-z0-9_-]+\.end")
_SENTINEL_PATTERN_BYTES: re.Pattern[bytes] = re.compile(rb"myrm-sent-v1\.[A-Za-z0-9_-]+\.end")

_NONCE_BYTES: int = 12
_KEY_BYTES: int = 32
_MAX_SENTINEL_TOKEN_LEN: int = 512


class SentinelManager:
    """Manages ephemeral in-memory sentinel vouchers for secrets.

    Encrypts raw secrets into unguessable, authenticated vouchers (AES-256-GCM)
    using a process-ephemeral 256-bit key. Vouchers cannot be reversed outside
    the current process lifetime. Fast lookups are cached in memory.
    """

    def __init__(self, key: bytes | None = None) -> None:
        """Initialize with an ephemeral 256-bit key.

        Args:
            key: Optional 32-byte key. If None, generated via os.urandom(32).
        """
        self._key: bytes = key if key is not None else os.urandom(_KEY_BYTES)
        self._sentinel_to_secret: dict[str, str] = {}
        self._secret_to_sentinel: dict[str, str] = {}
        self._bytes_sentinel_map: dict[bytes, bytes] = {}

    def create_sentinel(self, secret: str, metadata: dict[str, str] | None = None) -> str:
        """Create a sentinel voucher for a raw secret value.

        Args:
            secret: The raw secret (e.g. API key, token).
            metadata: Optional string metadata associated with this secret.

        Returns:
            The sentinel voucher string, formatted as 'myrm-sent-v1.<base64url>.end'.
        """
        if not secret:
            return ""

        # Return existing voucher if already issued for this exact secret in this process
        if secret in self._secret_to_sentinel:
            return self._secret_to_sentinel[secret]

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        payload = {
            "v": secret,
            "m": metadata or {},
        }
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        nonce = os.urandom(_NONCE_BYTES)
        ct = AESGCM(self._key).encrypt(nonce, json_bytes, None)

        # base64url without padding
        token = base64.urlsafe_b64encode(nonce + ct).decode("ascii").rstrip("=")
        sentinel = f"{SENTINEL_PREFIX}{token}{SENTINEL_SUFFIX}"

        self._sentinel_to_secret[sentinel] = secret
        self._secret_to_sentinel[secret] = sentinel
        self._bytes_sentinel_map[sentinel.encode("utf-8")] = secret.encode("utf-8")

        return sentinel

    def resolve_sentinel(self, sentinel: str) -> str | None:
        """Resolve a sentinel voucher back to its original raw secret.

        Fast path checks in-memory mapping. Fallback decrypts via AES-256-GCM.

        Args:
            sentinel: The sentinel voucher string.

        Returns:
            Original secret string, or None if invalid or forged.
        """
        if not sentinel or not sentinel.startswith(SENTINEL_PREFIX) or not sentinel.endswith(SENTINEL_SUFFIX):
            return None

        # Fast in-memory lookup
        if sentinel in self._sentinel_to_secret:
            return self._sentinel_to_secret[sentinel]

        # Authenticated decryption fallback
        raw_token = sentinel[len(SENTINEL_PREFIX) : -len(SENTINEL_SUFFIX)]
        padding_needed = (4 - len(raw_token) % 4) % 4
        padded = raw_token + "=" * padding_needed

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            raw_bytes = base64.urlsafe_b64decode(padded)
            if len(raw_bytes) < _NONCE_BYTES + 16:
                return None

            nonce = raw_bytes[:_NONCE_BYTES]
            ct = raw_bytes[_NONCE_BYTES:]
            decrypted = AESGCM(self._key).decrypt(nonce, ct, None)
            data = json.loads(decrypted.decode("utf-8"))
            secret_val = str(data.get("v", ""))
            if secret_val:
                self._sentinel_to_secret[sentinel] = secret_val
                self._bytes_sentinel_map[sentinel.encode("utf-8")] = secret_val.encode("utf-8")
                return secret_val
        except Exception:
            logger.debug("Failed to resolve forged or expired sentinel voucher: %s", sentinel[:20])

        return None

    def substitute_text(self, text: str) -> str:
        """Scan text and replace all valid sentinel vouchers with real secrets.

        Args:
            text: Arbitrary string containing zero or more sentinels.

        Returns:
            String with all resolved sentinels replaced by their true secrets.
        """
        if SENTINEL_PREFIX not in text:
            return text

        def _repl(match: re.Match[str]) -> str:
            token = match.group(0)
            resolved = self.resolve_sentinel(token)
            return resolved if resolved is not None else token

        return _SENTINEL_PATTERN.sub(_repl, text)

    def substitute_bytes(self, data: bytes) -> bytes:
        """Scan bytes and replace all valid sentinel vouchers with real secrets.

        Args:
            data: Arbitrary byte payload (e.g. HTTP body chunk).

        Returns:
            Bytes with all resolved sentinels replaced.
        """
        if b"myrm-sent-v1." not in data:
            return data

        def _repl(match: re.Match[bytes]) -> bytes:
            token_bytes = match.group(0)
            if token_bytes in self._bytes_sentinel_map:
                return self._bytes_sentinel_map[token_bytes]
            token_str = token_bytes.decode("ascii", errors="ignore")
            resolved = self.resolve_sentinel(token_str)
            if resolved is not None:
                return resolved.encode("utf-8")
            return token_bytes

        return _SENTINEL_PATTERN_BYTES.sub(_repl, data)

    def has_sentinels(self) -> bool:
        """Check if any sentinels are currently tracked in this manager."""
        return bool(self._sentinel_to_secret)


class StreamingSentinelScanner:
    """Sliding-window scanner for replacing sentinels across TCP/HTTP stream boundaries.

    Ensures that sentinels split across arbitrary chunk boundaries are reconstructed
    and replaced without buffering entire payloads in memory.
    """

    def __init__(self, manager: SentinelManager, max_window: int = _MAX_SENTINEL_TOKEN_LEN) -> None:
        """Initialize scanner with target manager and buffer window size."""
        self._manager: SentinelManager = manager
        self._max_window: int = max_window
        self._buffer: bytes = b""

    def feed(self, chunk: bytes) -> bytes:
        """Feed a new chunk of stream bytes and return ready replaced bytes.

        Maintains a small tail buffer to catch tokens spanning chunk boundaries.

        Args:
            chunk: Incoming stream bytes.

        Returns:
            Emitted bytes with complete sentinels safely substituted.
        """
        if not chunk:
            return b""

        self._buffer += chunk

        # If buffer is smaller than maximum token length, hold it for boundary reconstruction
        if len(self._buffer) <= self._max_window:
            return b""

        # Check if potential sentinel prefix is dangling near the end of the buffer
        tail_slice = self._buffer[-self._max_window :]
        prefix_idx = tail_slice.rfind(b"myrm-sent-v1.")

        if prefix_idx != -1:
            # A potential sentinel starts in the tail; hold back from that point
            split_point = len(self._buffer) - self._max_window + prefix_idx
            to_process = self._buffer[:split_point]
            self._buffer = self._buffer[split_point:]
        else:
            # No partial sentinel in tail; process everything except the last 16 bytes
            safe_cut = max(0, len(self._buffer) - 16)
            to_process = self._buffer[:safe_cut]
            self._buffer = self._buffer[safe_cut:]

        return self._manager.substitute_bytes(to_process)

    def flush(self) -> bytes:
        """Flush any remaining bytes in the buffer with final substitution.

        Returns:
            All remaining substituted bytes.
        """
        remaining = self._buffer
        self._buffer = b""
        return self._manager.substitute_bytes(remaining)


def is_sentinel_voucher(val: str) -> bool:
    """Check if a string matches the sentinel voucher pattern."""
    return bool(val and val.startswith(SENTINEL_PREFIX) and val.endswith(SENTINEL_SUFFIX))


_GLOBAL_SENTINEL_MANAGER: SentinelManager | None = None


def get_global_sentinel_manager() -> SentinelManager:
    """Get or initialize the process-singleton SentinelManager."""
    global _GLOBAL_SENTINEL_MANAGER
    if _GLOBAL_SENTINEL_MANAGER is None:
        _GLOBAL_SENTINEL_MANAGER = SentinelManager()
    return _GLOBAL_SENTINEL_MANAGER

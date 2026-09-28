"""In-memory session-isolated ephemeral credential store.

[INPUT]
- .types::EphemeralCredential, EphemeralCredentialSummary, validate_credential_key

[OUTPUT]
- EphemeralCredentialStore: Thread-safe, session-isolated ephemeral credential vault.
- get_ephemeral_credential_store: Singleton getter for the store.

[POS]
core/security/ephemeral_credentials/store.py
Session-scoped ephemeral storage with automatic GC and physical zeroization.
"""

from __future__ import annotations

import logging
import threading
import uuid

from .types import EphemeralCredential, EphemeralCredentialSummary, validate_credential_key

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 60.0


class EphemeralCredentialStore:
    """Thread-safe in-memory store for session-scoped ephemeral credentials.

    Isolation:
    - Every credential is partitioned by `session_id`.
    - Handles are referenced by `$CRED_EPHEMERAL_HANDLE_{UUID}`.
    - Credentials are zeroized on consumption (if single-use) or on explicit session purge.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, EphemeralCredential]] = {}

    def store_credential(
        self,
        session_id: str,
        key: str,
        secret: str,
        *,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        single_use: bool = True,
    ) -> EphemeralCredential:
        """Store a new ephemeral credential and return its handle.

        Args:
            session_id: Bound agent session identifier.
            key: Credential key (e.g., 'DB_PASSWORD', 'API_KEY').
            secret: Plaintext secret content to protect.
            ttl_seconds: Lifetime before auto-expiration.
            single_use: Whether the credential should be physically zeroized after single read.

        Returns:
            EphemeralCredential: The created ephemeral credential entry.
        """
        valid_key = validate_credential_key(key)
        handle_id = f"cred_ephemeral_{uuid.uuid4().hex[:12]}"
        material = bytearray(secret.encode("utf-8"))

        entry = EphemeralCredential(
            handle_id=handle_id,
            session_id=session_id,
            key=valid_key,
            _material=material,
            ttl_seconds=ttl_seconds,
            single_use=single_use,
        )

        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {}
            self._sessions[session_id][handle_id] = entry

        logger.debug(
            "[EPHEMERAL_CREDENTIAL] Stored key '%s' under handle '%s' for session '%s' (TTL=%ss, single_use=%s)",
            valid_key,
            handle_id,
            session_id,
            ttl_seconds,
            single_use,
        )
        return entry

    def consume_credential(self, session_id: str, handle_id: str) -> str:
        """Resolve and atomically consume an ephemeral credential.

        If single_use is True, the credential is immediately physically wiped from memory.

        Raises:
            KeyError: If session or handle is not found.
            ValueError: If credential has expired or has already been consumed.
        """
        with self._lock:
            session_map = self._sessions.get(session_id)
            if not session_map or handle_id not in session_map:
                raise KeyError(f"Ephemeral credential handle '{handle_id}' not found in session '{session_id}'.")

            cred = session_map[handle_id]
            secret = cred.read_secret()

            if cred.single_use:
                cred.wipe()
                session_map.pop(handle_id, None)
                logger.debug(
                    "[EPHEMERAL_CREDENTIAL] Atomically consumed and zeroized handle '%s' in session '%s'",
                    handle_id,
                    session_id,
                )

            return secret

    def peek_summary(self, session_id: str, handle_id: str) -> EphemeralCredentialSummary | None:
        """Retrieve safe metadata summary for a credential handle."""
        with self._lock:
            session_map = self._sessions.get(session_id)
            if not session_map or handle_id not in session_map:
                return None
            cred = session_map[handle_id]
            return EphemeralCredentialSummary(
                handle_id=cred.handle_id,
                session_id=cred.session_id,
                key=cred.key,
                created_at=cred.created_at,
                expires_at=cred.expires_at,
                ttl_seconds=cred.ttl_seconds,
                single_use=cred.single_use,
                is_consumed=cred.is_consumed,
                is_expired=cred.is_expired,
            )

    def list_summaries(self, session_id: str) -> list[EphemeralCredentialSummary]:
        """List metadata summaries of active credentials for a given session."""
        with self._lock:
            session_map = self._sessions.get(session_id, {})
            now = EphemeralCredentialSummary
            summaries: list[EphemeralCredentialSummary] = []
            for cred in session_map.values():
                summaries.append(
                    now(
                        handle_id=cred.handle_id,
                        session_id=cred.session_id,
                        key=cred.key,
                        created_at=cred.created_at,
                        expires_at=cred.expires_at,
                        ttl_seconds=cred.ttl_seconds,
                        single_use=cred.single_use,
                        is_consumed=cred.is_consumed,
                        is_expired=cred.is_expired,
                    )
                )
            return summaries

    def revoke_credential(self, session_id: str, handle_id: str) -> bool:
        """Explicitly revoke and physically wipe an ephemeral credential."""
        with self._lock:
            session_map = self._sessions.get(session_id)
            if not session_map or handle_id not in session_map:
                return False
            cred = session_map.pop(handle_id)
            cred.wipe()
            logger.info(
                "[EPHEMERAL_CREDENTIAL] Revoked and zeroized handle '%s' in session '%s'",
                handle_id,
                session_id,
            )
            return True

    def purge_session(self, session_id: str) -> int:
        """Purge and zeroize all ephemeral credentials for a session."""
        with self._lock:
            session_map = self._sessions.pop(session_id, None)
            if not session_map:
                return 0
            count = 0
            for cred in session_map.values():
                cred.wipe()
                count += 1
            logger.info(
                "[EPHEMERAL_CREDENTIAL] Purged %d credentials for session '%s'",
                count,
                session_id,
            )
            return count

    def cleanup_expired(self) -> int:
        """Scan and zeroize all expired credentials across all sessions."""
        with self._lock:
            cleaned = 0
            for session_id, session_map in list(self._sessions.items()):
                for handle_id, cred in list(session_map.items()):
                    if cred.is_expired:
                        cred.wipe()
                        session_map.pop(handle_id, None)
                        cleaned += 1
                if not session_map:
                    self._sessions.pop(session_id, None)
            if cleaned > 0:
                logger.info("[EPHEMERAL_CREDENTIAL] Cleaned up and zeroized %d expired credentials", cleaned)
            return cleaned


_global_store: EphemeralCredentialStore | None = None
_store_lock = threading.Lock()


def get_ephemeral_credential_store() -> EphemeralCredentialStore:
    """Return the process-wide singleton store instance."""
    global _global_store
    if _global_store is None:
        with _store_lock:
            if _global_store is None:
                _global_store = EphemeralCredentialStore()
    return _global_store

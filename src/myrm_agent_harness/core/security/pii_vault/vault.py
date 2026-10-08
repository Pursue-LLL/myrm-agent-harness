"""Local PII mapping vault storing pseudonym-to-real bidirectional mappings in local memory.

[INPUT]
- session_id, placeholder, raw_value

[OUTPUT]
- LocalPiiMappingVault: purely local, session-isolated, encrypted or memory-only mapping store.

[POS]
Harness core security module for client-side privacy preservation (Local Mapping Vault).
Never sends mapping dictionaries to external LLMs or remote clouds.
"""

from __future__ import annotations

import threading


class LocalPiiMappingVault:
    """Thread-safe session-isolated vault for storing PII pseudonym mappings."""

    def __init__(self) -> None:
        self._placeholder_to_real: dict[str, dict[str, str]] = {}
        self._real_to_placeholder: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def store_mapping(self, session_id: str, placeholder: str, raw_value: str) -> None:
        """Store bidirectional mapping between placeholder and raw PII value."""
        with self._lock:
            if session_id not in self._placeholder_to_real:
                self._placeholder_to_real[session_id] = {}
                self._real_to_placeholder[session_id] = {}
            self._placeholder_to_real[session_id][placeholder] = raw_value
            self._real_to_placeholder[session_id][raw_value] = placeholder

    def get_real_value(self, session_id: str, placeholder: str) -> str | None:
        """Retrieve original raw PII value corresponding to placeholder."""
        with self._lock:
            session_map = self._placeholder_to_real.get(session_id)
            if not session_map:
                return None
            return session_map.get(placeholder)

    def get_placeholder(self, session_id: str, raw_value: str) -> str | None:
        """Retrieve existing placeholder for an already-mapped raw value."""
        with self._lock:
            session_map = self._real_to_placeholder.get(session_id)
            if not session_map:
                return None
            return session_map.get(raw_value)

    def list_mappings(self, session_id: str) -> dict[str, str]:
        """Return a copy of the placeholder-to-real dictionary for a session."""
        with self._lock:
            session_map = self._placeholder_to_real.get(session_id)
            if not session_map:
                return {}
            return dict(session_map)

    def clear_session(self, session_id: str) -> None:
        """Securely wipe all mappings for the specified session."""
        with self._lock:
            self._placeholder_to_real.pop(session_id, None)
            self._real_to_placeholder.pop(session_id, None)

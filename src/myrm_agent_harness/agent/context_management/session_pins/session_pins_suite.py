"""Main suite orchestrating persistent session pins, client sorting, and deep links.

[INPUT]
- persistence_file_path: Optional[str] storage path for pin persistence
- base_deeplink_url: str prefix for deep links

[OUTPUT]
- SessionPinsPersistedInSessionsSuite: Main orchestrator for persistent session pinning.

[POS]
Main suite orchestrating persistent session pins, client sorting, and deep links.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Dict, List, Optional
import uuid

from .session_pin_repository import SessionPinRepository
from .session_pin_types import (
    PinActionKind,
    SessionDeeplinkRoute,
    SessionPinState,
    SessionPinSyncReceipt,
)


class SessionPinsPersistedInSessionsSuite:
    """Orchestrates persistent session pins, cross-client synchronization, and deep link routing."""

    def __init__(
        self,
        persistence_file_path: Optional[str] = None,
        base_deeplink_scheme: str = "myrm://session",
    ) -> None:
        self._repository = SessionPinRepository(persistence_file_path=persistence_file_path)
        self._base_deeplink_scheme = base_deeplink_scheme.rstrip("/")
        self._receipts: List[SessionPinSyncReceipt] = []

    def pin_session(
        self,
        session_id: str,
        pin_order: int = 0,
        label: str = "",
    ) -> SessionPinSyncReceipt:
        """Pin a session and issue a synchronization receipt."""
        pin = self._repository.set_pin(
            session_id=session_id,
            is_pinned=True,
            pin_order=pin_order,
            pin_label=label,
        )
        return self._record_receipt(session_id=session_id, action=PinActionKind.PIN, is_pinned=True)

    def unpin_session(self, session_id: str) -> SessionPinSyncReceipt:
        """Unpin a session and issue a synchronization receipt."""
        self._repository.set_pin(
            session_id=session_id,
            is_pinned=False,
            pin_order=0,
            pin_label="",
        )
        return self._record_receipt(session_id=session_id, action=PinActionKind.UNPIN, is_pinned=False)

    def toggle_pin(self, session_id: str) -> SessionPinSyncReceipt:
        """Toggle session pin state."""
        existing = self._repository.get_pin(session_id)
        if existing and existing.is_pinned:
            return self.unpin_session(session_id)
        return self.pin_session(session_id)

    def is_session_pinned(self, session_id: str) -> bool:
        """Check if target session is actively pinned."""
        pin = self._repository.get_pin(session_id)
        return bool(pin and pin.is_pinned)

    def get_pinned_sessions(self) -> List[SessionPinState]:
        """Fetch all actively pinned sessions in prioritized order."""
        return self._repository.get_all_pinned_sessions()

    def sort_sessions(
        self,
        session_items: List[Dict[str, str | int | bool]],
        session_id_key: str = "session_id",
        updated_at_key: str = "updated_at_iso",
    ) -> List[Dict[str, str | int | bool]]:
        """Sort session items with pinned sessions first, then by updated timestamp."""
        return self._repository.sort_session_dictionaries(
            session_items=session_items,
            session_id_key=session_id_key,
            updated_at_key=updated_at_key,
        )

    def generate_session_deeplink(
        self,
        session_id: str,
        target_entry_id: Optional[str] = None,
    ) -> SessionDeeplinkRoute:
        """Generate a deterministic deep link URL for direct navigation."""
        path = f"/sessions/{session_id}"
        if target_entry_id:
            path += f"?entry={target_entry_id}"
        full_url = f"{self._base_deeplink_scheme}{path}"
        return SessionDeeplinkRoute(
            deeplink_url=full_url,
            session_id=session_id,
            target_entry_id=target_entry_id,
            route_path=path,
        )

    def _record_receipt(
        self,
        session_id: str,
        action: PinActionKind,
        is_pinned: bool,
    ) -> SessionPinSyncReceipt:
        """Generate and record a certified sync receipt."""
        pinned = self.get_pinned_sessions()
        sync_hash = hashlib.sha256(
            f"{session_id}:{action.value}:{is_pinned}:{len(pinned)}".encode("utf-8")
        ).hexdigest()[:16]

        receipt = SessionPinSyncReceipt(
            receipt_id=f"spr_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            action=action,
            is_pinned=is_pinned,
            total_pinned_sessions_count=len(pinned),
            sync_hash=sync_hash,
            synced_at_iso=datetime.now(timezone.utc).isoformat(),
        )
        self._receipts.append(receipt)
        return receipt

    def get_sync_receipts(self) -> List[SessionPinSyncReceipt]:
        """Retrieve audit history of all session pin sync receipts."""
        return list(self._receipts)

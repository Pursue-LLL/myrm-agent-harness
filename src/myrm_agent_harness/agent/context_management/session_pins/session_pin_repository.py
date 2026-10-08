"""Repository managing persistent session pin records, ordering, and synchronization.

[INPUT]
- SessionPinState from .session_pin_types

[OUTPUT]
- SessionPinRepository: Class managing session pin lifecycle, queries, and prioritized sort ordering.

[POS]
Repository managing persistent session pin records, ordering, and synchronization.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, List, Optional

from .session_pin_types import PinActionKind, SessionPinState


class SessionPinRepository:
    """Manages persistent session pins with high-performance query, mutation, and ordering."""

    def __init__(self, persistence_file_path: Optional[str] = None) -> None:
        self._persistence_file_path = persistence_file_path
        self._pins_by_session_id: Dict[str, SessionPinState] = {}
        if self._persistence_file_path:
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load stored pin states from disk if file exists."""
        if not self._persistence_file_path:
            return
        p = Path(self._persistence_file_path)
        if not p.exists() or not p.is_file():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for sid, record in data.items():
                    if isinstance(record, dict):
                        self._pins_by_session_id[sid] = SessionPinState(
                            session_id=sid,
                            is_pinned=bool(record.get("is_pinned", False)),
                            pinned_at_iso=record.get("pinned_at_iso"),
                            pin_order=int(record.get("pin_order", 0)),
                            pin_label=str(record.get("pin_label", "")),
                        )
        except Exception:
            pass

    def _save_to_disk(self) -> None:
        """Persist in-memory pin states to disk atomically."""
        if not self._persistence_file_path:
            return
        p = Path(self._persistence_file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        dump_dict: Dict[str, Dict[str, str | int | bool | None]] = {}
        for sid, pin in self._pins_by_session_id.items():
            dump_dict[sid] = {
                "session_id": pin.session_id,
                "is_pinned": pin.is_pinned,
                "pinned_at_iso": pin.pinned_at_iso,
                "pin_order": pin.pin_order,
                "pin_label": pin.pin_label,
            }
        tmp_p = p.with_name(f".{p.name}.tmp")
        tmp_p.write_text(json.dumps(dump_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_p.replace(p)

    def set_pin(
        self,
        session_id: str,
        is_pinned: bool,
        pin_order: int = 0,
        pin_label: str = "",
    ) -> SessionPinState:
        """Set or update persistent pin state for a session."""
        pinned_at = datetime.now(timezone.utc).isoformat() if is_pinned else None
        pin = SessionPinState(
            session_id=session_id,
            is_pinned=is_pinned,
            pinned_at_iso=pinned_at,
            pin_order=pin_order,
            pin_label=pin_label,
        )
        self._pins_by_session_id[session_id] = pin
        self._save_to_disk()
        return pin

    def get_pin(self, session_id: str) -> Optional[SessionPinState]:
        """Fetch pin record for session ID."""
        return self._pins_by_session_id.get(session_id)

    def get_all_pinned_sessions(self) -> List[SessionPinState]:
        """Return all actively pinned session records sorted by order and time."""
        pinned = [p for p in self._pins_by_session_id.values() if p.is_pinned]
        pinned.sort(key=lambda x: (x.pin_order, -(datetime.fromisoformat(x.pinned_at_iso).timestamp() if x.pinned_at_iso else 0)))
        return pinned

    def sort_session_dictionaries(
        self,
        session_items: List[Dict[str, str | int | bool]],
        session_id_key: str = "session_id",
        updated_at_key: str = "updated_at_iso",
    ) -> List[Dict[str, str | int | bool]]:
        """Sort session dictionaries: pinned first (by pin_order, pinned_at), then unpinned by updated_at."""
        def sort_key(item: Dict[str, str | int | bool]) -> tuple[int, int, float]:
            sid = str(item.get(session_id_key, ""))
            pin = self.get_pin(sid)
            is_pin = 0 if (pin and pin.is_pinned) else 1
            order = pin.pin_order if (pin and pin.is_pinned) else 999999
            # Timestamp for secondary sorting (descending, so negate)
            ts = 0.0
            if pin and pin.is_pinned and pin.pinned_at_iso:
                try:
                    ts = datetime.fromisoformat(pin.pinned_at_iso).timestamp()
                except Exception:
                    pass
            elif updated_at_key in item and isinstance(item[updated_at_key], str):
                try:
                    ts = datetime.fromisoformat(str(item[updated_at_key])).timestamp()
                except Exception:
                    pass
            return (is_pin, order, -ts)

        return sorted(session_items, key=sort_key)

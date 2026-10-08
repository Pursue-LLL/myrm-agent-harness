"""Idempotency key generation and execution receipt caching.

[INPUT]
- session_id, tool_name, arguments, sequence from tool dispatch pipeline

[OUTPUT]
- compute_idempotency_key: Deterministic SHA-256 hash generator
- IdempotencyReceiptCache: Thread-safe in-memory receipt storage

[POS]
Harness security idempotency module. Prevents duplicate external execution during
retries or crash recovery by binding immutable keys to receipts.
"""

from __future__ import annotations

import hashlib
import json
import threading

from myrm_agent_harness.core.security.side_effect_gate.types import (
    ActionArguments,
    ActionArgumentValue,
    ActionReceipt,
)


def _serialize_canonical_value(val: ActionArgumentValue) -> str:
    """Recursively convert argument value to canonical JSON representation."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, list):
        items_str = ",".join(json.dumps(x, ensure_ascii=False) for x in sorted(val))
        return f"[{items_str}]"
    if isinstance(val, dict):
        pairs_str = ",".join(
            f"{json.dumps(k, ensure_ascii=False)}:{json.dumps(v, ensure_ascii=False)}"
            for k, v in sorted(val.items())
        )
        return f"{{{pairs_str}}}"
    return json.dumps(str(val), ensure_ascii=False)


def compute_idempotency_key(
    session_id: str,
    tool_name: str,
    arguments: ActionArguments,
    sequence: int = 0,
) -> str:
    """Generate a deterministic 32-character SHA-256 idempotency key."""
    canonical_pairs = [
        f"{json.dumps(k, ensure_ascii=False)}:{_serialize_canonical_value(v)}"
        for k, v in sorted(arguments.items())
    ]
    canonical_payload = f"{{{','.join(canonical_pairs)}}}"
    raw_material = f"{session_id}:{tool_name}:{sequence}:{canonical_payload}".encode()
    digest = hashlib.sha256(raw_material).hexdigest()
    return f"idem_{digest[:32]}"


class IdempotencyReceiptCache:
    """Thread-safe storage for external action execution receipts."""

    def __init__(self) -> None:
        self._receipts: dict[str, ActionReceipt] = {}
        self._lock = threading.Lock()

    def get_receipt(self, idempotency_key: str) -> ActionReceipt | None:
        """Retrieve existing receipt by idempotency key."""
        with self._lock:
            return self._receipts.get(idempotency_key)

    def has_receipt(self, idempotency_key: str) -> bool:
        """Check whether an action has already produced a valid receipt."""
        with self._lock:
            return idempotency_key in self._receipts

    def register_receipt(self, receipt: ActionReceipt) -> None:
        """Register completed external execution receipt."""
        with self._lock:
            self._receipts[receipt.idempotency_key] = receipt

    def list_receipts(self) -> list[ActionReceipt]:
        """List all currently recorded execution receipts."""
        with self._lock:
            return list(self._receipts.values())

    def clear(self) -> None:
        """Clear all receipts from cache."""
        with self._lock:
            self._receipts.clear()

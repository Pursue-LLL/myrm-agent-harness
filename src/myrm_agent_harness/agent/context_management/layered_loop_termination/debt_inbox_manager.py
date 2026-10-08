"""Manager for consumable debt inbox and model response debt accounting."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import List, Optional

from .layered_loop_types import DebtInboxItem, DebtKind


class DebtInboxManager:
    """Tracks both model response debts and queued consumable message debts."""

    def __init__(self) -> None:
        self._model_debts_count: int = 0
        self._inbox_queue: List[DebtInboxItem] = []

    @property
    def model_debt_count(self) -> int:
        """Count of pending model response obligations (e.g., tool execution completed, waiting for model)."""
        return self._model_debts_count

    @property
    def message_debt_count(self) -> int:
        """Count of pending unconsumed messages in the next-step inbox."""
        return sum(1 for item in self._inbox_queue if not item.consumed)

    def record_model_debt_incurred(self) -> None:
        """Incur a model debt (e.g. after a tool finishes, model owes a follow-up answer)."""
        self._model_debts_count += 1

    def record_model_debt_satisfied(self) -> None:
        """Satisfy and decrement model debt (e.g. model produced assistant message without tool calls)."""
        if self._model_debts_count > 0:
            self._model_debts_count -= 1

    def clear_model_debts(self) -> None:
        """Reset model debts (e.g. on turn reset or abort)."""
        self._model_debts_count = 0

    def enqueue_message_debt(
        self,
        kind: DebtKind,
        source: str,
        payload_text: str,
    ) -> DebtInboxItem:
        """Enqueue an actionable consumable payload into the inbox.

        Rule: Continuation must be data-driven. The loop will not continue without
        concrete data waiting in this queue.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        seed = f"{kind.value}:{source}:{payload_text}:{time.time()}"
        debt_id = f"debt-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:10]}"

        item = DebtInboxItem(
            debt_id=debt_id,
            kind=kind,
            source=source,
            payload_text=payload_text,
            timestamp_iso=now_iso,
            consumed=False,
        )
        self._inbox_queue.append(item)
        return item

    def dequeue_next_debt(self) -> Optional[DebtInboxItem]:
        """Consume the next unconsumed debt item from the inbox queue."""
        for idx, item in enumerate(self._inbox_queue):
            if not item.consumed:
                # Mark consumed
                consumed_item = DebtInboxItem(
                    debt_id=item.debt_id,
                    kind=item.kind,
                    source=item.source,
                    payload_text=item.payload_text,
                    timestamp_iso=item.timestamp_iso,
                    consumed=True,
                )
                self._inbox_queue[idx] = consumed_item
                return consumed_item
        return None

    def get_pending_debts(self) -> List[DebtInboxItem]:
        """Return all active unconsumed debt items."""
        return [item for item in self._inbox_queue if not item.consumed]

    def is_debt_free(self) -> bool:
        """Verify whether both model debts and message debts are completely satisfied."""
        return self._model_debts_count == 0 and self.message_debt_count == 0

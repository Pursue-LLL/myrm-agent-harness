# [POS]: src/myrm_agent_harness/toolkits/memory/ephemeral_delta/reconciler.py
# [INPUT]: delta_store.py (EphemeralDeltaStore), models.py (EphemeralDeltaItem, ReconciliationBatchReport)
# [OUTPUT]: EphemeralDeltaReconciler

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Awaitable, Callable

from myrm_agent_harness.toolkits.memory.ephemeral_delta.delta_store import (
    EphemeralDeltaStore,
)
from myrm_agent_harness.toolkits.memory.ephemeral_delta.models import (
    EphemeralDeltaItem,
    ReconciliationBatchReport,
)

logger = logging.getLogger(__name__)


class EphemeralDeltaReconciler:
    """Asynchronous reconciliation loop for persisting transient session deltas.

    At session close or unload time, active deltas are collapsed via LWW and
    persisted into the durable memory store (SQLite / Markdown profile). Next
    session's frozen SystemPrompt snapshot will seamlessly include these facts.
    """

    async def reconcile_session(
        self,
        session_id: str,
        store: EphemeralDeltaStore,
        persist_callback: (
            Callable[[list[EphemeralDeltaItem]], Awaitable[None] | None] | None
        ) = None,
    ) -> ReconciliationBatchReport:
        """Collapse active deltas and flush them into durable storage."""
        start_time = time.perf_counter()

        raw_deltas = store.get_all_raw_deltas(session_id)
        active_deltas = store.get_active_deltas(session_id)

        overridden_count = max(0, len(raw_deltas) - len(active_deltas))
        persisted_keys = [item.target_key for item in active_deltas]

        if persist_callback is not None and active_deltas:
            res = persist_callback(active_deltas)
            if inspect.isawaitable(res):
                await res

        store.mark_reconciled(session_id)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        report = ReconciliationBatchReport(
            session_id=session_id,
            reconciled_count=len(active_deltas),
            overridden_count=overridden_count,
            persisted_keys=persisted_keys,
            elapsed_ms=round(elapsed_ms, 2),
        )

        logger.info(
            "Reconciled session %s deltas: %d persisted, %d overridden in %.2fms",
            session_id,
            report.reconciled_count,
            report.overridden_count,
            report.elapsed_ms,
        )
        return report

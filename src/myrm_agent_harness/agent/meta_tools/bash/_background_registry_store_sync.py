"""Durable store write-through helpers for background bash registry.

[INPUT]
- agent.meta_tools.bash._background_types::BackgroundProcessInfo (POS: job snapshot)
- agent.meta_tools.bash._background_job_store (POS: BSDL SQLite ledger)

[OUTPUT]
- persist_vault_log_ref: Write spill basename to Store once
- persist_terminal_state: Mark job terminal in Store

[POS]
Extracted from BackgroundProcessRegistry to keep registry file under maintainability limits.
"""

from __future__ import annotations

import logging
import time

from myrm_agent_harness.agent.meta_tools.bash._background_types import BackgroundProcessInfo

logger = logging.getLogger(__name__)


def persist_vault_log_ref(info: BackgroundProcessInfo) -> None:
    from myrm_agent_harness.agent.meta_tools.bash._background_job_store import get_background_job_store

    store = get_background_job_store()
    ref = info.vault_log_ref
    if store is None or not ref:
        return
    try:
        store.set_vault_log_ref(info.job_id, ref)
    except Exception as exc:
        logger.warning(
            "Background job store vault_log_ref update failed job=%s: %s",
            info.job_id,
            exc,
        )


def persist_terminal_state(info: BackgroundProcessInfo) -> None:
    from myrm_agent_harness.agent.meta_tools.bash._background_job_store import get_background_job_store
    from myrm_agent_harness.agent.meta_tools.bash._background_job_store_core import BackgroundJobStoreStatus

    store = get_background_job_store()
    if store is None:
        return

    status_map: dict[str, BackgroundJobStoreStatus] = {
        "running": "running",
        "exited": "exited",
        "killed": "killed",
    }
    store_status: BackgroundJobStoreStatus = status_map.get(info.status, "exited")
    try:
        store.update_terminal(
            info.job_id,
            status=store_status,
            exit_code=info.exit_code,
            error_category=info.error_category,
            completed_at=time.time() if info.status != "running" else None,
            vault_log_ref=info.vault_log_ref,
        )
    except Exception as exc:
        logger.warning("Background job store terminal update failed job=%s: %s", info.job_id, exc)


__all__ = ["persist_terminal_state", "persist_vault_log_ref"]

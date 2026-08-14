"""Session-end privacy context re-establishment for memory-write PII protection.

``cleanup_run`` clears the security/policy/store/closure ContextVars before the
fire-and-forget session-end cleanup task runs, so end_session flush and
auto-extraction would otherwise persist memories without any PII protection.
This module rebuilds them from the agent's persisted ``SecurityConfig`` and the
last run context, and restores the previous values afterwards.

[INPUT]
- agent.middlewares._session_context::set/get_security_config/pseudonym_store (POS: session-scoped security ContextVars)
- core.security.persistence.content_scan::set/get_pii_pseudonymizer (POS: context-local regex PII closure)
- agent._internals.run_lifecycle::_init_pseudonym_store (POS: context-local PseudonymStore + closure init)

[OUTPUT]
- reestablish_privacy_context(agent): rebuild the privacy context, snapshotting previous values
- teardown_privacy_context(restore): restore the snapshot after cleanup work finishes

[POS]
Session-end privacy context helper. Guarantees fire-and-forget memory writes
persist with the same PII protection as in-run writes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.agent.security.detection.pseudonym_store import (
        PseudonymStore,
    )
    from myrm_agent_harness.agent.security.types import SecurityConfig
    from myrm_agent_harness.core.security.persistence.content_scan import (
        PseudonymizeFn,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PrivacyContextRestore:
    """Snapshot of the privacy ContextVars before re-establishment."""

    restored: bool
    prev_security: SecurityConfig | None = None
    prev_store: PseudonymStore | None = None
    prev_pseudonymizer: PseudonymizeFn | None = None


def reestablish_privacy_context(agent: object) -> PrivacyContextRestore:
    """Re-establish the privacy context for session-end memory writes.

    Reads ``SecurityConfig`` from the agent's persisted config and
    ``workspace_path`` from the last run context, then re-initializes the
    PseudonymStore and regex PII closure. Returns a snapshot of the previous
    ContextVar values so :func:`teardown_privacy_context` can restore them.
    """
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_pseudonym_store,
        get_security_config,
        set_pseudonym_store,
        set_security_config,
    )
    from myrm_agent_harness.core.security.persistence.content_scan import (
        get_pii_pseudonymizer,
        set_pii_pseudonymizer,
    )

    if get_security_config() is not None:
        return PrivacyContextRestore(restored=False)

    security_config = getattr(getattr(agent, "config", None), "security_config", None)
    privacy_policy = getattr(security_config, "privacy_policy", None)
    if security_config is None or privacy_policy is None or not privacy_policy.enabled:
        return PrivacyContextRestore(restored=False)

    workspace_path = (getattr(agent, "_last_context", None) or {}).get("workspace_path")
    if not workspace_path:
        logger.warning("Privacy context not re-established: workspace_path missing from last run context")
        return PrivacyContextRestore(restored=False)

    from myrm_agent_harness.agent._internals.run_lifecycle import (
        _init_pseudonym_store,
    )

    prev_security = get_security_config()
    prev_store = get_pseudonym_store()
    prev_pseudonymizer = get_pii_pseudonymizer()
    set_security_config(security_config)
    try:
        _init_pseudonym_store(str(workspace_path))
    except Exception as exc:
        logger.warning("Pseudonym store re-init failed: %s", exc)
        set_pseudonym_store(prev_store)
        set_security_config(prev_security)
        set_pii_pseudonymizer(prev_pseudonymizer)
        return PrivacyContextRestore(restored=False)
    return PrivacyContextRestore(
        restored=True,
        prev_security=prev_security,
        prev_store=prev_store,
        prev_pseudonymizer=prev_pseudonymizer,
    )


def teardown_privacy_context(restore: PrivacyContextRestore) -> None:
    """Restore the privacy ContextVars captured by re-establishment."""
    if not restore.restored:
        return
    from myrm_agent_harness.agent.middlewares._session_context import (
        set_pseudonym_store,
        set_security_config,
    )
    from myrm_agent_harness.core.security.persistence.content_scan import (
        set_pii_pseudonymizer,
    )

    set_pseudonym_store(restore.prev_store)
    set_security_config(restore.prev_security)
    set_pii_pseudonymizer(restore.prev_pseudonymizer)

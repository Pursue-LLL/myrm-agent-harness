"""Runtime invariant mode configuration from environment.

[INPUT]
- os.environ MYRM_INVARIANT_MODE

[OUTPUT]
- get_invariant_mode: Resolve InvariantMode (STRICT / WARN / DISABLED)

[POS]
Single source for production vs development invariant enforcement policy.
"""

from __future__ import annotations

import os

from myrm_agent_harness.observability.invariants.registry import InvariantMode

_ENV_KEY = "MYRM_INVARIANT_MODE"


def get_invariant_mode() -> InvariantMode:
    """Return invariant enforcement mode from ``MYRM_INVARIANT_MODE`` (default DISABLED)."""
    raw = os.environ.get(_ENV_KEY, InvariantMode.DISABLED.value).strip().upper()
    if not raw:
        return InvariantMode.DISABLED
    try:
        return InvariantMode(raw)
    except ValueError:
        return InvariantMode.DISABLED

"""One-time runtime invariant registry bootstrap.

[INPUT]
- core_pack::install_core_invariants

[OUTPUT]
- ensure_runtime_invariants_installed: Idempotent registry companion installation

[POS]
Lazy boot hook invoked before log integrity checks in production read paths.
"""

from __future__ import annotations

_INSTALLED = False


def ensure_runtime_invariants_installed() -> None:
    """Install core + log integrity invariant companions once per process."""
    global _INSTALLED
    if _INSTALLED:
        return
    from myrm_agent_harness.observability.invariants.core_pack import install_core_invariants

    install_core_invariants()
    _INSTALLED = True

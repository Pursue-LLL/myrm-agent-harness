"""The Doctor probe registry is exactly the set the product ships.

Probes self-register through side-effect imports in ``diagnostics/__init__.py``; no module
imports a probe's symbols, so a dropped import silently removes a probe from ``/health/doctor``.
This test pins the full set so that regression is loud.
"""

from __future__ import annotations

from myrm_agent_harness.observability.diagnostics.manager import _diagnostic_hooks

EXPECTED_DOCTOR_PROBES = frozenset(
    {
        "check_gateway_runtime_health",
        "check_network_health",
        "check_workspace_storage_health",
        "check_database_health",
        "check_qdrant_health",
        "check_tokenizer_health",
        "check_hook_health",
        "check_desktop_permissions_health",
        "check_local_trace_export_audit",
        "check_supply_chain_health",
        "check_system_exhaustion",
        "check_system_resources",
    }
)


def test_doctor_registry_is_exactly_the_shipped_probe_set() -> None:
    names = [hook.__name__ for hook in _diagnostic_hooks]
    assert len(names) == len(set(names)), "a probe was registered twice"
    assert set(names) == EXPECTED_DOCTOR_PROBES

"""Install guard — dual-wheel install readiness probe and post-install verification.

[INPUT]
- install_guard.probe (POS: Source vs compiled distribution readiness)
- install_guard._generated.core_ip_manifest (POS: Generated core IP import path list)

[OUTPUT]
- DistributionMode, assert_distribution_ready, get_distribution_mode, is_compiled_distribution

[POS]
Runtime domain for proprietary dual-wheel packaging: manifest imports, install probe, platform key, verify CLI.
"""

from myrm_agent_harness.runtime.install_guard.probe import (
    DistributionMode,
    DistributionNotReadyError,
    assert_distribution_ready,
    get_distribution_mode,
    is_compiled_distribution,
)

__all__ = [
    "DistributionMode",
    "DistributionNotReadyError",
    "assert_distribution_ready",
    "get_distribution_mode",
    "is_compiled_distribution",
]

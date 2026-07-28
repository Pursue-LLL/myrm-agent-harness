"""Distribution subsystem — compiled core wheel probe, manifest, and install verification.

[INPUT]
- distribution.probe (POS: Source vs compiled distribution readiness)
- distribution.core_ip_manifest (POS: Generated core IP import path list)

[OUTPUT]
- DistributionMode, assert_distribution_ready, get_distribution_mode, is_compiled_distribution

[POS]
Domain subpackage for dual-wheel release packaging: manifest, probe, platform key, install verify.
"""

from myrm_agent_harness.distribution.probe import (
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

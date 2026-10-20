"""Local loopback proxy bypass, probe validation, and Surge/Clash self-healing suite.

[OUTPUT]
- HealthStatus: State classification of local loopback health.
- ProxySoftwareKind: Known proxy software types (Surge, Clash, Clash Verge, Generic).
- ProxyEnvironmentSnapshot: Snapshot of active system proxy environment variables.
- LoopbackProbeResult: Detailed outcome of loopback endpoint probes.
- ProxyRemediationRule: Actionable bypass directive for operator proxy configs.
- ProxyEnvironmentGuard: Static environment guard and NO_PROXY injector.
- LoopbackProbe: Async TCP probe and proxy header inspector.
- SurgeClashSelfHealer: In-app direct transport builder and remediation card synthesizer.

[INPUT]
- __future__

[OUTPUT]
- (模块级副作用与注册)

[POS]
Local loopback proxy bypass, probe validation, and Surge/Clash self-healing suite.
"""

from __future__ import annotations

from myrm_agent_harness.core.network.loopback_probe import LoopbackProbe
from myrm_agent_harness.core.network.loopback_types import (
    HealthStatus,
    LoopbackProbeResult,
    ProxyEnvironmentSnapshot,
    ProxyRemediationRule,
    ProxySoftwareKind,
)
from myrm_agent_harness.core.network.proxy_environment_guard import (
    ProxyEnvironmentGuard,
)
from myrm_agent_harness.core.network.surge_clash_healer import (
    SurgeClashSelfHealer,
)

__all__ = [
    "HealthStatus",
    "LoopbackProbe",
    "LoopbackProbeResult",
    "ProxyEnvironmentGuard",
    "ProxyEnvironmentSnapshot",
    "ProxyRemediationRule",
    "ProxySoftwareKind",
    "SurgeClashSelfHealer",
]

"""Egress security and proxy substitution layer.

[INPUT]
- core.security.egress.proxy_server::EphemeralCaManager, LoopbackEgressProxy
  (POS: 环回出口代理与瞬时 CA 管理层)
- core.security.egress.sentinel::SENTINEL_PREFIX, SENTINEL_SUFFIX, SentinelManager,
  StreamingSentinelScanner, get_global_sentinel_manager, is_sentinel_voucher
  (POS: 进程级瞬时密钥令牌化层)

[OUTPUT]
- LoopbackEgressProxy, EphemeralCaManager and the sentinel voucher helpers

[POS]
Public surface of the core egress security package. Provides process-ephemeral sentinel
voucher encoding/decoding and loopback egress proxy substitution for secrets in agent
sandbox environments.
"""

from __future__ import annotations

from .proxy_server import EphemeralCaManager, LoopbackEgressProxy
from .sentinel import (
    SENTINEL_PREFIX,
    SENTINEL_SUFFIX,
    SentinelManager,
    StreamingSentinelScanner,
    get_global_sentinel_manager,
    is_sentinel_voucher,
)
from .spend_governor import (
    SPEND_VOUCHER_PREFIX,
    SPEND_VOUCHER_SUFFIX,
    SpendCommitResult,
    SpendGovernor,
    SpendGovernorConfig,
    SpendLease,
    SpendLeaseResult,
    is_spend_voucher,
)
from .tainted_gateway import (
    TaintedEgressBlockedException,
    TaintedEgressDecision,
    TaintedEgressGateway,
    is_current_egress_tainted,
    set_current_egress_tainted,
)

__all__ = [
    "EphemeralCaManager",
    "LoopbackEgressProxy",
    "SENTINEL_PREFIX",
    "SENTINEL_SUFFIX",
    "SPEND_VOUCHER_PREFIX",
    "SPEND_VOUCHER_SUFFIX",
    "SentinelManager",
    "SpendCommitResult",
    "SpendGovernor",
    "SpendGovernorConfig",
    "SpendLease",
    "SpendLeaseResult",
    "StreamingSentinelScanner",
    "TaintedEgressBlockedException",
    "TaintedEgressDecision",
    "TaintedEgressGateway",
    "get_global_sentinel_manager",
    "is_current_egress_tainted",
    "is_sentinel_voucher",
    "is_spend_voucher",
    "set_current_egress_tainted",
]

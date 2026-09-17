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

__all__ = [
    "EphemeralCaManager",
    "LoopbackEgressProxy",
    "SENTINEL_PREFIX",
    "SENTINEL_SUFFIX",
    "SentinelManager",
    "StreamingSentinelScanner",
    "get_global_sentinel_manager",
    "is_sentinel_voucher",
]

"""Egress security and proxy substitution layer.

Provides process-ephemeral sentinel voucher encoding/decoding and loopback
egress proxy substitution for secrets in agent sandbox environments.
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

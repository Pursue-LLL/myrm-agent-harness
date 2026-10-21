"""Hierarchical Concurrency and Fan-Out Throttle Isolation Suite.

Multi-tier quota isolation matrix and dynamic session-level fan-out suppression
to prevent cascading server failures and resource exhaustion.

[INPUT]
- fanout_braking_sentinel
- hierarchical_quota_matrix
- throttle_types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Hierarchical Concurrency and Fan-Out Throttle Isolation Suite.
"""

from .fanout_braking_sentinel import FanOutBrakingSentinel
from .hierarchical_quota_matrix import HierarchicalQuotaMatrix
from .throttle_types import (
    BrakeSeverity,
    FanOutBrakeVerdict,
    FanOutLimitExceededError,
    ResourceLeaseTicket,
    ResourceTier,
    TierQuotaConfig,
)

__all__ = [
    "BrakeSeverity",
    "FanOutBrakingSentinel",
    "FanOutBrakeVerdict",
    "FanOutLimitExceededError",
    "HierarchicalQuotaMatrix",
    "ResourceLeaseTicket",
    "ResourceTier",
    "TierQuotaConfig",
]

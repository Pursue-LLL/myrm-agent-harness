"""Subagent Concurrency & Tool Budget Adaptive Scaling package (Item 31).

[INPUT]
- migrator
- types
- watermark_guard

[OUTPUT]
- (模块级副作用与注册)

[POS]
Subagent Concurrency & Tool Budget Adaptive Scaling package (Item 31).

"""

from .migrator import ConfigUpgradeMigrator
from .types import (
    DEFAULT_MAX_CHILDREN_PER_AGENT,
    DEFAULT_MAX_DESCENDANTS_PER_RUN,
    DEFAULT_SCALED_CONCURRENCY,
    DEFAULT_SCALED_MAX_TURNS,
    DEFAULT_WATERMARK_THRESHOLD_RATIO,
    LEGACY_DEFAULT_CONCURRENCY,
    LEGACY_DEFAULT_MAX_TURNS,
    ConfigMigrationResult,
    WatermarkAlert,
)
from .watermark_guard import SubagentWatermarkGuard

__all__ = [
    "ConfigMigrationResult",
    "ConfigUpgradeMigrator",
    "DEFAULT_MAX_CHILDREN_PER_AGENT",
    "DEFAULT_MAX_DESCENDANTS_PER_RUN",
    "DEFAULT_SCALED_CONCURRENCY",
    "DEFAULT_SCALED_MAX_TURNS",
    "DEFAULT_WATERMARK_THRESHOLD_RATIO",
    "LEGACY_DEFAULT_CONCURRENCY",
    "LEGACY_DEFAULT_MAX_TURNS",
    "SubagentWatermarkGuard",
    "WatermarkAlert",
]

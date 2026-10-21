"""Feature Flags unified management system.

Provides centralized feature flag registration, lifecycle management,
and runtime querying. Framework layer provides the engine; business layer
registers features and assembles deploy-mode-specific defaults.

Usage (business layer):
    from myrm_agent_harness.core.features import registry, init_features, get_features
    from myrm_agent_harness.core.features.types import FeatureSpec, FeatureStage

    # 1. Register features at startup
    registry.register(FeatureSpec(
        id="my_feature",
        key="my_feature",
        stage=FeatureStage.EXPERIMENTAL,
        default_enabled=False,
        description="My cool feature",
        experimental_info=ExperimentalInfo(name="My Feature", description="..."),
    ))

    # 2. Initialize with config
    init_features(defaults={"my_feature": True}, overrides=user_config)

    # 3. Query anywhere
    if get_features().enabled("my_feature"):
        ...
"""

from __future__ import annotations

import logging

from . import registry
from .feature_set import FeatureSet
from .types import DeprecationInfo, ExperimentalInfo, FeatureSpec, FeatureStage

logger = logging.getLogger(__name__)

_feature_set: FeatureSet | None = None


def init_features(
    defaults: dict[str, bool] | None = None,
    overrides: dict[str, bool] | None = None,
) -> FeatureSet:
    """Initialize the global FeatureSet from config layers.

    Must be called once at application startup, after all features are registered.
    Returns the created FeatureSet.
    """
    global _feature_set
    _feature_set = FeatureSet.from_config(defaults=defaults, overrides=overrides)

    warnings = _feature_set.warnings()
    for w in warnings:
        logger.warning("Feature flag: %s", w)

    non_defaults = _feature_set.enabled_non_default()
    if non_defaults:
        items = ", ".join(f"{fid}={'on' if en else 'off'}" for fid, en in non_defaults)
        logger.info("Feature flags (non-default): %s", items)

    return _feature_set


def get_features() -> FeatureSet:
    """Get the global FeatureSet. Raises RuntimeError if not initialized."""
    if _feature_set is None:
        raise RuntimeError("Feature flags not initialized. Call init_features() at startup.")
    return _feature_set


def is_initialized() -> bool:
    """Check if feature flags have been initialized."""
    return _feature_set is not None


def _reset_for_testing() -> None:
    """Reset global state. Only for unit tests."""
    global _feature_set
    _feature_set = None
    registry._reset_for_testing()


__all__ = [
    "DeprecationInfo",
    "ExperimentalInfo",
    "FeatureSet",
    "FeatureSpec",
    "FeatureStage",
    "get_features",
    "init_features",
    "is_initialized",
    "registry",
]

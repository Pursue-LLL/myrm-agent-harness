"""FeatureSet — runtime container for enabled feature flags.

[INPUT]

[OUTPUT]
- FeatureSet with enabled/disabled query, dependency normalization, warnings

[POS]
Runtime layer. Created once at startup via from_config(), stored as module singleton.
Framework does not know about deploy modes; business layer assembles defaults.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from . import registry
from .types import FeatureSpec, FeatureStage

logger = logging.getLogger(__name__)


class FeatureSet:
    """Manages the effective set of enabled features at runtime.

    Two-layer merge: defaults → overrides.
    Business layer assembles defaults based on deploy mode.
    User overrides come from persistent config.
    """

    __slots__ = ("_enabled", "_warnings")

    def __init__(self, enabled: set[str]) -> None:
        self._enabled: set[str] = enabled
        self._warnings: list[str] = []

    @classmethod
    def from_config(
        cls,
        defaults: dict[str, bool] | None = None,
        overrides: dict[str, bool] | None = None,
    ) -> FeatureSet:
        """Build a FeatureSet from registry defaults + config layers.

        1. Start with each FeatureSpec's default_enabled
        2. Apply `defaults` overrides (deploy-mode-specific, from business layer)
        3. Apply `overrides` (user configuration)
        4. Normalize dependencies
        5. Collect warnings
        """
        enabled: set[str] = set()
        warnings: list[str] = []

        for spec in registry.all_specs():
            if spec.stage == FeatureStage.REMOVED:
                continue
            if spec.default_enabled:
                enabled.add(spec.id)

        if defaults:
            for key, value in defaults.items():
                spec = registry.get(key) or registry.get_by_key(key)
                if spec is None:
                    warnings.append(f"Unknown feature key in defaults: '{key}'")
                    continue
                if spec.stage == FeatureStage.REMOVED:
                    continue
                if value:
                    enabled.add(spec.id)
                else:
                    enabled.discard(spec.id)

        if overrides:
            for key, value in overrides.items():
                spec = registry.get(key) or registry.get_by_key(key)
                if spec is None:
                    warnings.append(f"Unknown feature key in overrides: '{key}'")
                    continue
                if spec.stage == FeatureStage.REMOVED:
                    warnings.append(f"Feature '{key}' has been removed and will be ignored")
                    continue
                if value:
                    enabled.add(spec.id)
                else:
                    enabled.discard(spec.id)

        feature_set = cls(enabled)
        feature_set._warnings = warnings
        feature_set._normalize_dependencies()
        feature_set._collect_stability_warnings()
        return feature_set

    def enabled(self, feature_id: str) -> bool:
        """Check if a feature is enabled."""
        return feature_id in self._enabled

    def enable(self, feature_id: str) -> None:
        """Enable a feature at runtime."""
        spec = registry.get(feature_id)
        if spec is None:
            raise ValueError(f"Unknown feature: '{feature_id}'")
        if spec.stage == FeatureStage.REMOVED:
            raise ValueError(f"Feature '{feature_id}' has been removed")
        self._enabled.add(feature_id)
        self._normalize_dependencies()

    def disable(self, feature_id: str) -> None:
        """Disable a feature at runtime."""
        self._enabled.discard(feature_id)

    def enabled_features(self) -> list[str]:
        """Return sorted list of all enabled feature ids."""
        return sorted(self._enabled)

    def enabled_non_default(self) -> list[tuple[str, bool]]:
        """Return features whose state differs from their default.

        Useful for telemetry — only report non-default states.
        Returns list of (feature_id, is_enabled) tuples.
        """
        result: list[tuple[str, bool]] = []
        for spec in registry.all_specs():
            if spec.stage == FeatureStage.REMOVED:
                continue
            is_enabled = spec.id in self._enabled
            if is_enabled != spec.default_enabled:
                result.append((spec.id, is_enabled))
        return result

    def warnings(self) -> list[str]:
        """Return all collected warnings (unknown keys, unstable features, etc.)."""
        return list(self._warnings)

    def experimental_features(self) -> Iterator[FeatureSpec]:
        """Yield enabled experimental features with their metadata."""
        for spec in registry.experimental_specs():
            if spec.id in self._enabled:
                yield spec

    def to_dict(self) -> dict[str, bool]:
        """Export current state as a dict for persistence or API response."""
        result: dict[str, bool] = {}
        for spec in registry.all_specs():
            if spec.stage == FeatureStage.REMOVED:
                continue
            result[spec.id] = spec.id in self._enabled
        return result

    def _normalize_dependencies(self) -> None:
        """Auto-enable features required by enabled features (declared in depends_on)."""
        changed = True
        while changed:
            changed = False
            for spec in registry.all_specs():
                if spec.id not in self._enabled:
                    continue
                for dep_id in spec.depends_on:
                    if dep_id not in self._enabled:
                        dep_spec = registry.get(dep_id)
                        if dep_spec and dep_spec.stage != FeatureStage.REMOVED:
                            self._enabled.add(dep_id)
                            changed = True
                            logger.info(
                                "Auto-enabled '%s' (required by '%s')",
                                dep_id,
                                spec.id,
                            )

    def _collect_stability_warnings(self) -> None:
        """Warn about enabled UnderDevelopment or Deprecated features."""
        for spec in registry.all_specs():
            if spec.id not in self._enabled:
                continue
            if spec.stage == FeatureStage.UNDER_DEVELOPMENT:
                self._warnings.append(f"Feature '{spec.id}' is under development and may behave unpredictably")
            elif spec.stage == FeatureStage.DEPRECATED:
                hint = ""
                if spec.deprecation_info:
                    hint = f" {spec.deprecation_info.migration_hint}"
                self._warnings.append(f"Feature '{spec.id}' is deprecated.{hint}")

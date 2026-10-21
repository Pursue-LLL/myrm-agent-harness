"""Feature registry — global singleton for feature spec registration and lookup.

[INPUT]

[OUTPUT]
- Thread-safe global registry for querying feature specifications

[POS]
Core infrastructure. Modules register their features at import/startup time.
Business layer registers additional features before initializing the FeatureSet.
"""

from __future__ import annotations

import logging
import threading

from .types import FeatureSpec, FeatureStage

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_specs: dict[str, FeatureSpec] = {}
_key_to_id: dict[str, str] = {}


def register(spec: FeatureSpec) -> None:
    """Register a feature specification.

    Raises ValueError if the id or key already exists with a different spec.
    """
    with _lock:
        if spec.id in _specs:
            existing = _specs[spec.id]
            if existing != spec:
                raise ValueError(f"Feature '{spec.id}' already registered with different spec")
            return

        if spec.key in _key_to_id:
            existing_id = _key_to_id[spec.key]
            raise ValueError(f"Feature key '{spec.key}' already used by feature '{existing_id}'")

        _specs[spec.id] = spec
        _key_to_id[spec.key] = spec.id


def get(feature_id: str) -> FeatureSpec | None:
    """Look up a feature spec by id."""
    return _specs.get(feature_id)


def get_by_key(key: str) -> FeatureSpec | None:
    """Look up a feature spec by its config key."""
    feature_id = _key_to_id.get(key)
    if feature_id is None:
        return None
    return _specs.get(feature_id)


def all_specs() -> list[FeatureSpec]:
    """Return all registered feature specs, sorted by id."""
    return sorted(_specs.values(), key=lambda s: s.id)


def experimental_specs() -> list[FeatureSpec]:
    """Return only EXPERIMENTAL stage features."""
    return [s for s in _specs.values() if s.stage == FeatureStage.EXPERIMENTAL]


def deprecated_specs() -> list[FeatureSpec]:
    """Return only DEPRECATED stage features."""
    return [s for s in _specs.values() if s.stage == FeatureStage.DEPRECATED]


def is_known_key(key: str) -> bool:
    """Check if a config key maps to a known feature."""
    return key in _key_to_id


def _reset_for_testing() -> None:
    """Clear all registrations. Only for unit tests."""
    with _lock:
        _specs.clear()
        _key_to_id.clear()

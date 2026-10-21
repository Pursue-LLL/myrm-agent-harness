"""Registry and persistence manager for Per-App Operating Profiles.

Provides atomic JSON-based disk persistence, in-memory caching, and multi-index
lookup by application ID, display name, or bundle identifier.

[INPUT]
- __future__
- json
- tempfile
- time
- pathlib
- profile_types

[OUTPUT]
- AppProfileRegistry

[POS]
Registry and persistence manager for Per-App Operating Profiles.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from .profile_types import (
    AppObservation,
    AppOperatingProfile,
    FalsificationStatus,
    ObservationTier,
)


class AppProfileRegistry:
    """Manages the lifecycle and persistence of AppOperatingProfile instances."""

    def __init__(self, storage_dir: Path | str) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, AppOperatingProfile] = {}
        self._name_index: dict[str, str] = {}
        self._bundle_index: dict[str, str] = {}
        self.reload_all()

    def reload_all(self) -> None:
        """Scan storage directory and reload all JSON profile manifests into memory."""
        self._cache.clear()
        self._name_index.clear()
        self._bundle_index.clear()

        for file_path in self.storage_dir.glob("*.json"):
            try:
                profile = self._read_profile_file(file_path)
                self._index_profile(profile)
            except (json.JSONDecodeError, KeyError, OSError):
                # Tolerate unparseable files without crashing the registry
                continue

    def get_profile(self, identifier: str) -> AppOperatingProfile | None:
        """Find a profile by app_id, display_name, or bundle_id (case-insensitive)."""
        key = identifier.strip().lower()
        if key in self._cache:
            return self._cache[key]
        if key in self._name_index:
            return self._cache.get(self._name_index[key])
        if key in self._bundle_index:
            return self._cache.get(self._bundle_index[key])
        return None

    def register_or_update(self, profile: AppOperatingProfile) -> Path:
        """Atomically persist a profile to disk and refresh index mappings."""
        profile.updated_at = time.time()
        file_path = self.storage_dir / f"{profile.app_id.lower()}.json"

        data: dict[str, object] = {
            "app_id": profile.app_id,
            "display_name": profile.display_name,
            "bundle_id": profile.bundle_id,
            "executable_path": profile.executable_path,
            "deterministic_features": profile.deterministic_features,
            "observations": {
                k: self._serialize_observation(obs)
                for k, obs in profile.observations.items()
            },
            "schema_version": profile.schema_version,
            "updated_at": profile.updated_at,
        }

        # Atomic file write using temporary file and atomic replace
        with tempfile.NamedTemporaryFile(
            "w",
            dir=self.storage_dir,
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp_path = Path(tmp.name)

        tmp_path.replace(file_path)
        self._index_profile(profile)
        return file_path

    def list_profiles(self) -> list[AppOperatingProfile]:
        """Return a snapshot list of all cached profiles."""
        return list(self._cache.values())

    def _index_profile(self, profile: AppOperatingProfile) -> None:
        """Register profile into internal lookup indices."""
        app_key = profile.app_id.strip().lower()
        self._cache[app_key] = profile
        if profile.display_name:
            self._name_index[profile.display_name.strip().lower()] = app_key
        if profile.bundle_id:
            self._bundle_index[profile.bundle_id.strip().lower()] = app_key

    def _read_profile_file(self, file_path: Path) -> AppOperatingProfile:
        """Deserialize a profile JSON file into AppOperatingProfile domain model."""
        with file_path.open("r", encoding="utf-8") as f:
            raw_data = json.load(f)

        raw_features = raw_data.get("deterministic_features", {})
        features: dict[str, str] = {
            str(k): str(v) for k, v in raw_features.items()
        }

        raw_observations = raw_data.get("observations", {})
        observations: dict[str, AppObservation] = {}
        for k, raw_obs in raw_observations.items():
            observations[str(k)] = self._deserialize_observation(raw_obs)

        return AppOperatingProfile(
            app_id=str(raw_data.get("app_id", "")),
            display_name=str(raw_data.get("display_name", "")),
            bundle_id=str(raw_data.get("bundle_id", "")),
            executable_path=str(raw_data.get("executable_path", "")),
            deterministic_features=features,
            observations=observations,
            schema_version=int(raw_data.get("schema_version", 1)),
            updated_at=float(raw_data.get("updated_at", time.time())),
        )

    @staticmethod
    def _serialize_observation(obs: AppObservation) -> dict[str, object]:
        """Serialize an AppObservation to a JSON-compatible dictionary."""
        return {
            "observation_id": obs.observation_id,
            "app_id": obs.app_id,
            "feature_key": obs.feature_key,
            "statement": obs.statement,
            "tier": obs.tier.value,
            "status": obs.status.value,
            "is_ephemeral": obs.is_ephemeral,
            "can_convert_to_code": obs.can_convert_to_code,
            "code_hook_target": obs.code_hook_target,
            "supporting_apps": list(obs.supporting_apps),
            "created_at": obs.created_at,
            "updated_at": obs.updated_at,
        }

    @staticmethod
    def _deserialize_observation(data: dict[str, object]) -> AppObservation:
        """Deserialize a dictionary to an AppObservation instance."""
        supp_apps_raw = data.get("supporting_apps", [])
        supp_apps: tuple[str, ...] = tuple(
            str(x) for x in supp_apps_raw
        ) if isinstance(supp_apps_raw, list) else ()

        return AppObservation(
            observation_id=str(data.get("observation_id", "")),
            app_id=str(data.get("app_id", "")),
            feature_key=str(data.get("feature_key", "")),
            statement=str(data.get("statement", "")),
            tier=ObservationTier(str(data.get("tier", ObservationTier.PER_APP_STABLE.value))),
            status=FalsificationStatus(str(data.get("status", FalsificationStatus.ACTIVE.value))),
            is_ephemeral=bool(data.get("is_ephemeral", False)),
            can_convert_to_code=bool(data.get("can_convert_to_code", False)),
            code_hook_target=str(data.get("code_hook_target", "")),
            supporting_apps=supp_apps,
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )

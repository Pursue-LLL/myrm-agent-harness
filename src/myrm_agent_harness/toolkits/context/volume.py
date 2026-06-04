"""Context bundle volume layout.

[INPUT]
- pathlib::Path (POS: Python path library)
- .spec::VOLUME_LAYOUT_VERSION (POS: context bundle specification types)

[OUTPUT]
- VolumeLayout: resolved on-disk layout under MYRM_DATA_DIR / state_dir
- BUNDLE_MANIFEST_FILENAME: manifest file name at bundle root

[POS]
Maps a state directory to memory, harness, offload, and archive paths used by ContextBundleFacade.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .spec import VOLUME_LAYOUT_VERSION

BUNDLE_MANIFEST_FILENAME = "context_bundle_manifest.json"


@dataclass(frozen=True, slots=True)
class VolumeLayout:
    """On-disk layout for a single-user context bundle."""

    state_dir: Path
    memory_path: Path
    harness_path: Path
    qdrant_path: Path
    offload_root: Path
    archive_path: Path

    @classmethod
    def from_state_dir(cls, state_dir: str | Path) -> VolumeLayout:
        base = Path(state_dir).expanduser().resolve()
        harness = base / "harness"
        return cls(
            state_dir=base,
            memory_path=base / "memory",
            harness_path=harness,
            qdrant_path=base / "qdrant",
            offload_root=harness / ".context",
            archive_path=harness / "archives",
        )

    def ensure_directories(self) -> None:
        """Create bundle directories when missing (idempotent)."""
        for path in (
            self.memory_path,
            self.harness_path,
            self.qdrant_path,
            self.offload_root,
            self.archive_path,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def session_offload_dir(self, session_id: str) -> Path:
        safe_session = session_id.strip().replace("/", "_")
        return self.offload_root / safe_session

    def manifest_path(self) -> Path:
        return self.state_dir / BUNDLE_MANIFEST_FILENAME

    def to_manifest_dict(self, *, bundle_id: str, schema_version: int) -> dict[str, object]:
        return {
            "bundle_id": bundle_id,
            "schema_version": schema_version,
            "volume_layout_version": VOLUME_LAYOUT_VERSION,
            "state_dir": str(self.state_dir),
            "paths": {
                "memory": str(self.memory_path),
                "harness": str(self.harness_path),
                "qdrant": str(self.qdrant_path),
                "offload_root": str(self.offload_root),
                "archive": str(self.archive_path),
            },
        }

    def write_manifest(self, *, bundle_id: str, schema_version: int) -> Path:
        manifest_path = self.manifest_path()
        payload = self.to_manifest_dict(bundle_id=bundle_id, schema_version=schema_version)
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest_path

    @classmethod
    def read_manifest(cls, state_dir: str | Path) -> dict[str, object] | None:
        path = Path(state_dir).expanduser().resolve() / BUNDLE_MANIFEST_FILENAME
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return raw

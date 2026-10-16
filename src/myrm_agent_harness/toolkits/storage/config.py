"""Storage configuration


[INPUT]
- dataclasses::dataclass (POS: Python dataclass)
- os, pathlib::Path (POS: environment and path handling)

[OUTPUT]
- StorageConfig: storage configuration (root directory of the filesystem backend)
- storage_config: global storage configuration singleton

[POS]
Storage configuration module. The storage root is derived from MYRM_DATA_DIR, which the deployment layer injects
(in cloud sandboxes it points at the persistent volume), and falls back to ~/.myrm/storage. Depended on by the
storage factory and by consumers that need the root directory on disk.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _get_default_storage_path() -> str:
    """Get default storage path from MYRM_DATA_DIR env var or fallback.

    Priority:
    1. MYRM_DATA_DIR environment variable + /storage
    2. ~/.myrm/storage (default)
    """
    data_dir = os.environ.get("MYRM_DATA_DIR", "").strip()
    if data_dir:
        return str(Path(data_dir).expanduser().resolve() / "storage")
    return str(Path.home() / ".myrm" / "storage")


@dataclass
class StorageConfig:
    """Storage configuration."""

    # The key layout under the root belongs to the business layer; this layer only resolves keys against it.
    base_path: str = field(default_factory=_get_default_storage_path)

    def get_base_path(self) -> Path:
        """Absolute storage root; a relative ``base_path`` is resolved against the current working directory."""
        path = Path(self.base_path)
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()


# Global configuration instance
storage_config = StorageConfig()

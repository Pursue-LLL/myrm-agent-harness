"""Storage configuration


[INPUT]
- dataclasses::dataclass (POS: Python dataclass)
- enum::Enum (POS: Python enum type)

[OUTPUT]
- StorageMode: storage mode enum (LOCAL)
- LocalStorageConfig: local storage configuration
- StorageConfig: unified storage configuration (contains various storage configs)
- storage_config: global storage configuration singleton

[POS]
Storage configuration module. All configs injected via constructor parameters with sensible defaults.
Design principle: framework layer only includes local storage implementation; cloud storage provided
by business layer via dependency injection. As the config layer, depended on by storage factory and backends.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class StorageMode(StrEnum):
    """StorageMode"""

    LOCAL = "local"  # LocalFile系统
    PERSISTENT = "persistent"  # 容器内持久化Storage（/persistent + /workspace）


def _get_storage_mode() -> StorageMode:
    """Auto检测StorageMode

    检测Whether in 容器内运行（/persistent DirectoryExists）。
    """
    from pathlib import Path

    if Path("/persistent").exists():
        return StorageMode.PERSISTENT
    return StorageMode.LOCAL


def _get_default_storage_path() -> str:
    """Get default storage path from MYRM_DATA_DIR env var or fallback.

    Priority:
    1. MYRM_DATA_DIR environment variable + /storage
    2. ~/.myrm/storage (default)
    """
    import os

    data_dir = os.environ.get("MYRM_DATA_DIR", "").strip()
    if data_dir:
        return str(Path(data_dir).expanduser().resolve() / "storage")
    return str(Path.home() / ".myrm" / "storage")


@dataclass
class LocalStorageConfig:
    """LocalStorageConfigure"""

    # Storage根Directory（从 MYRM_DATA_DIR 环境变量读取，默认 ~/.myrm/storage）
    # Storage桶结构：skills/, users/{user_id}/
    # Note：workspaces 属于沙箱， not  in Storage桶 in
    base_path: str = field(default_factory=_get_default_storage_path)


@dataclass
class PersistentStorageConfig:
    """容器内持久化StorageConfigure"""

    persistent_path: str = "/persistent"
    workspace_path: str = "/workspace"


@dataclass
class StorageConfig:
    """StorageConfigure"""

    mode: StorageMode = field(default_factory=_get_storage_mode)

    local: LocalStorageConfig = field(default_factory=LocalStorageConfig)

    persistent: PersistentStorageConfig = field(default_factory=PersistentStorageConfig)

    def get_local_base_path(self) -> Path:
        """GetLocalStorage 绝对Path

        绝对Path directly Return；相对Path基于 cwd Parse。
        """
        path = Path(self.local.base_path)
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()


# GlobalConfigureInstance
storage_config = StorageConfig()

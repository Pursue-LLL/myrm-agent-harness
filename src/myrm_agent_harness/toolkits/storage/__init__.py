"""Storage abstraction layer.

Provides a unified storage CRUD interface decoupled from business logic.
The framework ships LocalStorageBackend (rooted at MYRM_DATA_DIR/storage); any other
backend is injected by the business layer through StorageProvider.
"""

from .base import FileInfo, StorageError, StorageProvider
from .config import StorageConfig, storage_config
from .factory import (
    create_storage_provider,
    get_storage_provider,
    set_storage_provider,
)
from .local import LocalStorageBackend
from .paths import (
    FILE_METADATA_SUFFIX,
    FILES_ROOT_PREFIX,
    SKILL_METADATA_FILE,
    SKILLS_ROOT_PREFIX,
    get_file_metadata_path,
    get_file_storage_path,
    get_skill_file_path,
    get_skill_metadata_path,
    get_skill_storage_path,
    get_skills_type_prefix,
    get_user_config_path,
    get_user_files_prefix,
    get_user_skill_config_path,
)
from .types import FilePurpose, SkillType

__all__ = [
    "FILES_ROOT_PREFIX",
    "FILE_METADATA_SUFFIX",
    "SKILLS_ROOT_PREFIX",
    "SKILL_METADATA_FILE",
    "FileInfo",
    "FilePurpose",
    "LocalStorageBackend",
    "SkillType",
    "StorageConfig",
    "StorageError",
    "StorageProvider",
    "create_storage_provider",
    "get_file_metadata_path",
    "get_file_storage_path",
    "get_skill_file_path",
    "get_skill_metadata_path",
    "get_skill_storage_path",
    "get_skills_type_prefix",
    "get_storage_provider",
    "get_user_config_path",
    "get_user_files_prefix",
    "get_user_skill_config_path",
    "set_storage_provider",
    "storage_config",
]

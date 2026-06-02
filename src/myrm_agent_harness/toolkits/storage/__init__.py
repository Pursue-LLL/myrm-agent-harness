"""Storage abstraction layer.

provides统一 Storage CRUD Interface， and 业务逻辑解耦。
框架层只built-inLocalStorageimplements，CloudStorage由业务层 via depends on注入provides。
"""

from .base import FileInfo, StorageError, StorageProvider
from .cached import CachedStorageProvider, CacheStats
from .config import StorageConfig, StorageMode, storage_config
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
    STORAGE_REF_PREFIX,
    USERS_ROOT_PREFIX,
    create_storage_ref,
    extract_file_id_from_path,
    extract_user_id_from_path,
    get_all_files_prefix,
    get_file_metadata_path,
    get_file_storage_path,
    get_skill_content_path,
    get_skill_file_path,
    get_skill_metadata_path,
    get_skill_storage_path,
    get_skills_type_prefix,
    get_user_config_path,
    get_user_files_prefix,
    get_user_skill_config_path,
    is_storage_ref,
    is_valid_file_path,
    is_valid_skill_path,
    parse_storage_ref,
)
from .types import FilePurpose, SkillType

__all__ = [
    # Path常量
    "FILES_ROOT_PREFIX",
    "FILE_METADATA_SUFFIX",
    "SKILLS_ROOT_PREFIX",
    "SKILL_METADATA_FILE",
    "STORAGE_REF_PREFIX",
    "USERS_ROOT_PREFIX",
    "CacheStats",
    "CachedStorageProvider",
    "FileInfo",
    # Type
    "FilePurpose",
    "LocalStorageBackend",
    "SkillType",
    "StorageConfig",
    "StorageError",
    "StorageMode",
    # coreInterface
    "StorageProvider",
    # 工厂
    "create_storage_provider",
    # Storage引用
    "create_storage_ref",
    "extract_file_id_from_path",
    "extract_user_id_from_path",
    "get_all_files_prefix",
    "get_file_metadata_path",
    # PathGenerate
    "get_file_storage_path",
    "get_skill_content_path",
    "get_skill_file_path",
    "get_skill_metadata_path",
    "get_skill_storage_path",
    "get_skills_type_prefix",
    "get_storage_provider",
    "get_user_config_path",
    "get_user_files_prefix",
    "get_user_skill_config_path",
    "is_storage_ref",
    # PathValidate/Parse
    "is_valid_file_path",
    "is_valid_skill_path",
    "parse_storage_ref",
    "set_storage_provider",
    "storage_config",
]

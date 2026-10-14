"""Storage path utility module


[INPUT]
- types::FilePurpose, SkillType (POS: file purpose and skill type enums)

[OUTPUT]
- FILES_ROOT_PREFIX, SKILLS_ROOT_PREFIX: path prefix constants
- get_file_storage_path(): generate file storage path
- get_skill_storage_path(): generate skill storage path
- get_user_skill_config_path(): generate user skill config path

[POS]
Storage path utility module. Centrally manages storage system path generation, ensuring all
components use consistent path formats. Defines path structures for files and skills
with generation functions. As the path convention layer, depended on by all storage-related modules.
"""

from __future__ import annotations

from .types import FilePurpose, SkillType

# ============================================================================
# Path prefix constants
# ============================================================================

# File storage root prefix
FILES_ROOT_PREFIX = "files"

# Skill storage root prefix
SKILLS_ROOT_PREFIX = "skills"

# File metadata suffix
FILE_METADATA_SUFFIX = ".meta.json"

# Skill metadata filename
SKILL_METADATA_FILE = "_metadata.json"


# ============================================================================
# File path generation
# ============================================================================


def get_file_storage_path(file_id: str, purpose: FilePurpose) -> str:
    """Get file storage path.

    Unified format: files/{purpose}/{file_id}

    Args:
        file_id: File ID
        purpose: File purpose

    Returns:
        Storage path string

    Examples:
        >>> get_file_storage_path("file_abc", FilePurpose.UPLOAD)
        'files/uploads/file_abc'
        >>> get_file_storage_path("file_xyz", FilePurpose.GENERATED)
        'files/generated/file_xyz'
    """
    purpose_dir = _get_purpose_directory(purpose)
    return f"{FILES_ROOT_PREFIX}/{purpose_dir}/{file_id}"


def get_file_metadata_path(storage_path: str) -> str:
    """Get file metadata storage path.

    Args:
        storage_path: File storage path

    Returns:
        Metadata file path

    Examples:
        >>> get_file_metadata_path("files/uploads/file_abc")
        'files/uploads/file_abc.meta.json'
    """
    return f"{storage_path}{FILE_METADATA_SUFFIX}"


def get_user_files_prefix(purpose: FilePurpose | None = None) -> str:
    """Get workspace file search prefix.

    Args:
        purpose: Optional, limit to specific purpose

    Returns:
        Search prefix string

    Examples:
        >>> get_user_files_prefix()
        'files/'
        >>> get_user_files_prefix(FilePurpose.GENERATED)
        'files/generated/'
    """
    if purpose:
        purpose_dir = _get_purpose_directory(purpose)
        return f"{FILES_ROOT_PREFIX}/{purpose_dir}/"
    return f"{FILES_ROOT_PREFIX}/"


_PURPOSE_DIR_MAP: dict[FilePurpose, str] = {
    FilePurpose.UPLOAD: "uploads",
    FilePurpose.GENERATED: "generated",
    FilePurpose.SKILL: "skill",
}


def _get_purpose_directory(purpose: FilePurpose) -> str:
    """Convert FilePurpose to directory name.

    Args:
        purpose: File purpose enum

    Returns:
        Directory name string
    """
    return _PURPOSE_DIR_MAP.get(purpose, "other")


# ============================================================================
# Skill path generation
# ============================================================================


def get_skill_storage_path(skill_type: SkillType, skill_id: str) -> str:
    """Get skill storage path.

    Format: skills/{type}/{skill_id}

    Args:
        skill_type: Skill type
        skill_id: Skill ID

    Returns:
        Storage path string

    Examples:
        >>> get_skill_storage_path(SkillType.PREBUILT, "pdf-generator")
        'skills/prebuilt/pdf-generator'
    """
    return f"{SKILLS_ROOT_PREFIX}/{skill_type.value}/{skill_id}"


def get_skills_type_prefix(skill_type: SkillType) -> str:
    """Get search prefix for a specific skill type.

    Args:
        skill_type: Skill type

    Returns:
        Search prefix string
    """
    return f"{SKILLS_ROOT_PREFIX}/{skill_type.value}/"


def get_skill_file_path(skill_type: SkillType, skill_id: str, filename: str) -> str:
    """Get path to a specific file within a skill.

    Args:
        skill_type: Skill type
        skill_id: Skill ID
        filename: Filename

    Returns:
        Full file path

    Examples:
        >>> get_skill_file_path(SkillType.PREBUILT, "pdf-generator", "SKILL.md")
        'skills/prebuilt/pdf-generator/SKILL.md'
    """
    return f"{get_skill_storage_path(skill_type, skill_id)}/{filename}"


def get_skill_metadata_path(skill_type: SkillType, skill_id: str) -> str:
    """Get skill metadata file path.

    Args:
        skill_type: Skill type
        skill_id: Skill ID

    Returns:
        Metadata file path

    Examples:
        >>> get_skill_metadata_path(SkillType.PREBUILT, "pdf-generator")
        'skills/prebuilt/pdf-generator/_metadata.json'
    """
    return f"{get_skill_storage_path(skill_type, skill_id)}/{SKILL_METADATA_FILE}"


# ============================================================================
# User config path generation
# ============================================================================


def get_user_config_path(config_name: str) -> str:
    """Get workspace config file path.

    Format: config/{config_name}.json

    Args:
        config_name: Config name (without extension)

    Returns:
        Config file path

    Examples:
        >>> get_user_config_path("skills")
        'config/skills.json'
    """
    return f"config/{config_name}.json"


def get_user_skill_config_path() -> str:
    """Get workspace skill config file path.

    Returns:
        Skill config file path
    """
    return get_user_config_path("skills")

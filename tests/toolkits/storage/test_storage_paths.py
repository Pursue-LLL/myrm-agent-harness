"""Tests for storage path utilities.

Covers path generation, parsing, validation, and extraction functions.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.storage.paths import (
    FILE_METADATA_SUFFIX,
    FILES_ROOT_PREFIX,
    SKILLS_ROOT_PREFIX,
    STORAGE_REF_PREFIX,
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
from myrm_agent_harness.toolkits.storage.types import FilePurpose, SkillType


class TestFilePathGeneration:
    def test_get_file_storage_path_upload(self) -> None:
        path = get_file_storage_path("file_abc", FilePurpose.UPLOAD)
        assert path == "files/uploads/file_abc"

    def test_get_file_storage_path_generated(self) -> None:
        path = get_file_storage_path("file_xyz", FilePurpose.GENERATED)
        assert path == "files/generated/file_xyz"

    def test_get_file_storage_path_skill(self) -> None:
        path = get_file_storage_path("file_xyz", FilePurpose.SKILL)
        assert path == "files/skill/file_xyz"

    def test_get_file_metadata_path(self) -> None:
        path = get_file_metadata_path("files/uploads/file_abc")
        assert path == f"files/uploads/file_abc{FILE_METADATA_SUFFIX}"

    def test_get_user_files_prefix_all(self) -> None:
        prefix = get_user_files_prefix()
        assert prefix == "files/"

    def test_get_user_files_prefix_with_purpose(self) -> None:
        prefix = get_user_files_prefix(FilePurpose.GENERATED)
        assert prefix == "files/generated/"

    def test_get_all_files_prefix(self) -> None:
        assert get_all_files_prefix() == f"{FILES_ROOT_PREFIX}/"


class TestSkillPathGeneration:
    def test_get_skill_storage_path_prebuilt(self) -> None:
        path = get_skill_storage_path(SkillType.PREBUILT, "pdf-generator")
        assert path == "skills/prebuilt/pdf-generator"

    def test_get_skill_storage_path_local(self) -> None:
        path = get_skill_storage_path(SkillType.LOCAL, "my-custom-skill")
        assert path == "skills/local/my-custom-skill"

    def test_get_skill_content_path(self) -> None:
        path = get_skill_content_path("skills/prebuilt/pdf-generator")
        assert path == "skills/prebuilt/pdf-generator/SKILL.md"

    def test_get_skills_type_prefix(self) -> None:
        prefix = get_skills_type_prefix(SkillType.PREBUILT)
        assert prefix == f"{SKILLS_ROOT_PREFIX}/prebuilt/"

    def test_get_skill_file_path(self) -> None:
        path = get_skill_file_path(SkillType.PREBUILT, "pdf-generator", "SKILL.md")
        assert path == "skills/prebuilt/pdf-generator/SKILL.md"

    def test_get_skill_metadata_path(self) -> None:
        path = get_skill_metadata_path(SkillType.PREBUILT, "pdf-generator")
        assert path == "skills/prebuilt/pdf-generator/_metadata.json"


class TestUserConfigPaths:
    def test_get_user_config_path(self) -> None:
        path = get_user_config_path("skills")
        assert path == "config/skills.json"

    def test_get_user_skill_config_path(self) -> None:
        path = get_user_skill_config_path()
        assert path == "config/skills.json"


class TestStorageRef:
    def test_create_storage_ref(self) -> None:
        ref = create_storage_ref("files/user123/generated/file_abc")
        assert ref == f"{STORAGE_REF_PREFIX}files/user123/generated/file_abc"

    def test_parse_storage_ref_valid(self) -> None:
        result = parse_storage_ref(f"{STORAGE_REF_PREFIX}files/user123/generated/file_abc")
        assert result == "files/user123/generated/file_abc"

    def test_parse_storage_ref_invalid(self) -> None:
        assert parse_storage_ref("invalid") is None

    def test_is_storage_ref_true(self) -> None:
        assert is_storage_ref(f"{STORAGE_REF_PREFIX}files/test") is True

    def test_is_storage_ref_false(self) -> None:
        assert is_storage_ref("not_a_ref") is False


class TestPathValidation:
    def test_is_valid_file_path(self) -> None:
        assert is_valid_file_path("files/user123/uploads/file_abc") is True
        assert is_valid_file_path("skills/prebuilt/test") is False
        assert is_valid_file_path("random/path") is False

    def test_is_valid_skill_path(self) -> None:
        assert is_valid_skill_path("skills/prebuilt/test") is True
        assert is_valid_skill_path("files/user123/test") is False


class TestPathExtraction:
    def test_extract_user_id(self) -> None:
        assert extract_user_id_from_path("files/user123/uploads/file_abc") == "user123"

    def test_extract_user_id_invalid(self) -> None:
        assert extract_user_id_from_path("invalid/path") is None

    def test_extract_user_id_short_path(self) -> None:
        assert extract_user_id_from_path("files/") == ""

    def test_extract_file_id(self) -> None:
        assert extract_file_id_from_path("files/user123/uploads/file_abc") == "file_abc"

    def test_extract_file_id_with_metadata_suffix(self) -> None:
        assert extract_file_id_from_path(f"files/user123/uploads/file_abc{FILE_METADATA_SUFFIX}") == "file_abc"

    def test_extract_file_id_invalid(self) -> None:
        assert extract_file_id_from_path("invalid/path") is None

    def test_extract_file_id_short_path(self) -> None:
        assert extract_file_id_from_path("files/user123/uploads") is None

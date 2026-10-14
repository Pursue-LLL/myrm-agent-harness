"""Tests for storage path utilities.

Covers path generation functions.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.storage.paths import (
    FILE_METADATA_SUFFIX,
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


class TestSkillPathGeneration:
    def test_get_skill_storage_path_prebuilt(self) -> None:
        path = get_skill_storage_path(SkillType.PREBUILT, "pdf-generator")
        assert path == "skills/prebuilt/pdf-generator"

    def test_get_skill_storage_path_local(self) -> None:
        path = get_skill_storage_path(SkillType.LOCAL, "my-custom-skill")
        assert path == "skills/local/my-custom-skill"

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

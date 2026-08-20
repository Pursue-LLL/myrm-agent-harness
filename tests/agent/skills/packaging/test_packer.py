import io
import zipfile
from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.packaging.packer import SkillPacker
from myrm_agent_harness.backends.skills.protocols import SkillBackend
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillTrust


@pytest.mark.asyncio
async def test_package_files_success():
    packer = SkillPacker()
    files = {
        "SKILL.md": b"---\nname: my_skill\nversion: 1.5.0\n---\n# My Skill",
        "script.py": "print('hello')",
    }

    result = packer.package_files("my_skill", "1.0.0", files)

    assert result.success
    assert result.filename == "my_skill_v1.5.0.zip"
    assert result.zip_content is not None

    # Verify ZIP content
    with zipfile.ZipFile(io.BytesIO(result.zip_content), "r") as zf:
        assert "my_skill/SKILL.md" in zf.namelist()
        assert "my_skill/script.py" in zf.namelist()
        assert zf.read("my_skill/script.py").decode("utf-8") == "print('hello')"


@pytest.mark.asyncio
async def test_package_files_missing_skill_md():
    packer = SkillPacker()
    files = {"script.py": "print('hello')"}

    result = packer.package_files("my_skill", "1.0.0", files)
    assert not result.success
    assert "SKILL.md" in result.error


@pytest.mark.asyncio
async def test_package_directory(tmp_path: Path):
    skill_dir = tmp_path / "test_dir_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test_dir_skill\n---", encoding="utf-8"
    )
    (skill_dir / "test.py").write_text("pass", encoding="utf-8")

    packer = SkillPacker()
    result = packer.package_directory(skill_dir)

    assert result.success
    assert result.filename == "test_dir_skill_v1.0.0.zip"

    with zipfile.ZipFile(io.BytesIO(result.zip_content), "r") as zf:
        assert "test_dir_skill/SKILL.md" in zf.namelist()
        assert "test_dir_skill/test.py" in zf.namelist()


@pytest.mark.asyncio
async def test_package_directory_empty(tmp_path: Path):
    packer = SkillPacker()
    result = packer.package_directory(tmp_path / "nonexistent")
    assert not result.success
    assert "目录为空或不存在" in result.error


class MockSkillBackend(SkillBackend):
    async def list_skills(self) -> list[SkillMetadata]:
        return []

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        if "backend_skill" in skill_ids:
            return [
                SkillMetadata(
                    name="backend_skill",
                    version="2.1.0",
                    description="",
                    storage_path="",
                    trust=SkillTrust.TRUSTED,
                )
            ]
        return []

    async def get_skill_content(self, skill_name: str) -> str:
        if skill_name == "backend_skill":
            return "---\nname: backend_skill\nversion: 2.1.0\n---\n# Content"
        raise FileNotFoundError()

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        if skill_name == "backend_skill" and path == "res.txt":
            return b"resource data"
        return None

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        if skill_name == "backend_skill":
            return ["res.txt"]
        return []


@pytest.mark.asyncio
async def test_package_as_agent_plugin_roundtrip():
    from myrm_agent_harness.agent.plugins.parser import AgentPluginParser

    packer = SkillPacker()
    files = {
        "SKILL.md": b"---\nname: my_test_skill\nversion: 1.2.0\ndescription: Test skill description\n---\n# My Test Skill Content",
        "scripts/helper.py": "def add(a, b): return a + b",
    }

    result = packer.package_as_agent_plugin(
        skill_name="my_test_skill",
        version="1.2.0",
        file_contents=files,
        description="A great test skill",
        keywords=["test", "demo"],
    )

    assert result.success
    assert result.filename == "my-test-skill_v1.2.0.zip"
    assert result.zip_content is not None

    # 反向自解测试：使用 AgentPluginParser 解析导出的 zip
    parser = AgentPluginParser()
    parse_result = parser.parse_zip(result.zip_content)

    assert parse_result.meta is not None
    assert parse_result.meta.name == "my-test-skill"
    assert parse_result.meta.version == "1.2.0"
    assert parse_result.meta.description == "A great test skill"
    assert parse_result.meta.keywords == ("test", "demo")

    # 验证技能解析结果
    assert len(parse_result.skills) == 1
    skill = parse_result.skills[0]
    assert skill.name == "my-test-skill"
    assert "scripts/helper.py" in skill.files
    assert (
        skill.files["scripts/helper.py"].decode("utf-8")
        == "def add(a, b): return a + b"
    )
    assert len(parse_result.diagnostics) == 0


@pytest.mark.asyncio
async def test_package_from_backend_not_found():
    backend = MockSkillBackend()
    packer = SkillPacker()

    result = await packer.package_from_backend(backend, "unknown_skill")
    assert not result.success
    assert "技能不存在" in result.error

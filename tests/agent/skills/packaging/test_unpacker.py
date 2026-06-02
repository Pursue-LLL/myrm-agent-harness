import io
import zipfile

from myrm_agent_harness.agent.skills.packaging.unpacker import SkillUnpacker


def test_unpack_success():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("my_skill/SKILL.md", "---\nname: my_skill\n---\n# My Skill")
        zf.writestr("my_skill/script.py", "print('hello')")

    zip_content = zip_buffer.getvalue()
    unpacker = SkillUnpacker()

    result = unpacker.unpack(zip_content)

    assert result.success
    assert result.skill_info is not None
    assert result.skill_info.name == "my_skill"
    assert result.files is not None
    assert "SKILL.md" in result.files
    assert "script.py" in result.files
    assert result.files["script.py"] == b"print('hello')"


def test_unpack_invalid_zip():
    unpacker = SkillUnpacker()
    result = unpacker.unpack(b"invalid zip data")

    assert not result.success
    assert result.skill_info is None
    assert result.files is None
    assert "无效的 ZIP 文件" in result.error


def test_unpack_forbidden_files_filtered():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("my_skill/SKILL.md", "---\nname: my_skill\n---")
        zf.writestr("my_skill/.env", "SECRET=123")

    zip_content = zip_buffer.getvalue()
    unpacker = SkillUnpacker()
    result = unpacker.unpack(zip_content)

    assert result.success
    # The .env file should be filtered out by safe_extract_zip with forbidden_check
    assert "SKILL.md" in result.files
    assert ".env" not in result.files

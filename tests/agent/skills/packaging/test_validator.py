import io
import zipfile

import pytest

from myrm_agent_harness.agent.skills.packaging.validator import (
    MAX_SKILL_ZIP_SIZE,
    is_forbidden_file,
    parse_skill_md,
    suggest_valid_skill_name,
    validate_skill_zip,
)


def _build_fake_pe_binary() -> bytes:
    payload = bytearray(128)
    payload[0:2] = b"MZ"
    payload[0x3C:0x40] = (0x40).to_bytes(4, "little")
    payload[0x40:0x44] = b"PE\x00\x00"
    return bytes(payload)


def test_suggest_valid_skill_name():
    assert suggest_valid_skill_name("My Skill") == "my-skill"
    assert suggest_valid_skill_name("123-skill") == "skill"
    assert suggest_valid_skill_name("---abc") == "abc"
    assert suggest_valid_skill_name("a!@#b") == "a-b"
    assert suggest_valid_skill_name("   ") == "my-skill"


def test_is_forbidden_file():
    assert is_forbidden_file("__pycache__/main.pyc")
    assert is_forbidden_file(".git/config")
    assert is_forbidden_file(".env")
    assert is_forbidden_file("node_modules/a.js")
    assert is_forbidden_file(".venv/bin/activate")
    assert is_forbidden_file("src/main.pyc")

    assert not is_forbidden_file("main.py")
    assert not is_forbidden_file("SKILL.md")
    assert not is_forbidden_file("test.env.example")


def test_parse_skill_md_yaml_front_matter():
    content = """---
name: "test_skill"
description: 'A test skill'
version: 2.0.0
author: Alice
---
# Test Skill
"""
    info = parse_skill_md(content)
    assert info.name == "test_skill"
    assert info.description == "A test skill"
    assert info.version == "2.0.0"
    assert info.author == "Alice"


def test_parse_skill_md_no_front_matter():
    content = """# My Awesome Skill
description: simple desc
"""
    info = parse_skill_md(content)
    assert info.name == "My Awesome Skill"
    assert info.description == "simple desc"
    assert info.version == "1.0.0"
    assert info.author is None


def test_validate_skill_zip_valid():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("test_skill/SKILL.md", "---\nname: test_skill\n---")
        zf.writestr("test_skill/main.py", "print('hello')")

    zip_content = zip_buffer.getvalue()
    info = validate_skill_zip(zip_content)

    assert info.is_valid
    assert info.name == "test_skill"
    assert "main.py" in info.files
    assert len(info.validation_errors) == 0


def test_validate_skill_zip_invalid_no_skill_md():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("test_skill/main.py", "print('hello')")

    zip_content = zip_buffer.getvalue()
    info = validate_skill_zip(zip_content)

    assert not info.is_valid
    assert any("SKILL.md" in e for e in info.validation_errors)


def test_validate_skill_zip_invalid_multiple_roots():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("test_skill/SKILL.md", "---\nname: test_skill\n---")
        zf.writestr("other_dir/main.py", "print('hello')")

    zip_content = zip_buffer.getvalue()
    info = validate_skill_zip(zip_content)

    assert not info.is_valid
    assert any("一个根目录" in e for e in info.validation_errors)


def test_validate_skill_zip_bad_zip():
    info = validate_skill_zip(b"not a zip file")
    assert not info.is_valid
    assert any("无效的 ZIP 文件" in e for e in info.validation_errors)


def test_validate_skill_zip_empty_zip():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED):
        pass
    info = validate_skill_zip(zip_buffer.getvalue())
    assert not info.is_valid
    assert any("ZIP 文件为空" in e for e in info.validation_errors)


def test_validate_skill_zip_too_large():
    # Make a dummy zip content larger than MAX_SKILL_ZIP_SIZE
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
        # Just create an empty file but pad the buffer
        zf.writestr("test_skill/SKILL.md", "---\nname: test\n---")

    # Pad to exceed size
    zip_content = zip_buffer.getvalue() + b"0" * (MAX_SKILL_ZIP_SIZE)
    info = validate_skill_zip(zip_content)

    assert not info.is_valid
    assert any("ZIP 文件过大" in e for e in info.validation_errors)


def test_validate_skill_zip_forbidden_files_are_ignored():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("test_skill/SKILL.md", "---\nname: test_skill\n---")
        zf.writestr("test_skill/.env", "SECRET=123")
        zf.writestr("test_skill/__pycache__/main.pyc", "binary")

    zip_content = zip_buffer.getvalue()
    info = validate_skill_zip(zip_content)

    assert info.is_valid
    # The forbidden files should not be listed in info.files
    assert len(info.files) == 1
    assert info.files[0] == "SKILL.md"


def test_validate_skill_zip_rejects_too_many_entries(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "myrm_agent_harness.agent.skills.packaging.validator.MAX_ZIP_ENTRY_COUNT",
        4,
    )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("test_skill/SKILL.md", "---\nname: test_skill\n---")
        for index in range(4):
            zf.writestr(f"test_skill/file-{index:04d}.txt", "")

    info = validate_skill_zip(zip_buffer.getvalue())

    assert not info.is_valid
    assert any("ZIP 文件条目数过多" in error for error in info.validation_errors)


def test_validate_skill_zip_allows_entry_count_at_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "myrm_agent_harness.agent.skills.packaging.validator.MAX_ZIP_ENTRY_COUNT",
        4,
    )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("test_skill/SKILL.md", "---\nname: test_skill\n---")
        for index in range(3):
            zf.writestr(f"test_skill/file-{index:04d}.txt", "")

    info = validate_skill_zip(zip_buffer.getvalue())

    assert info.is_valid


def test_validate_skill_zip_rejects_executable_binary_member():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("test_skill/SKILL.md", "---\nname: test_skill\n---")
        zf.writestr("test_skill/payload.bin", _build_fake_pe_binary())

    info = validate_skill_zip(zip_buffer.getvalue())

    assert not info.is_valid
    assert any("可执行二进制文件" in error for error in info.validation_errors)

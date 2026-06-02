"""Tests for StorageSkillBackend loading prebuilt skills.

Verifies that SKILL.md files with YAML frontmatter are correctly
parsed and loaded by StorageSkillBackend from a storage provider.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.skills import StorageSkillBackend
from myrm_agent_harness.backends.skills.types import SkillTrust
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend

PPTX_SKILL_MD = """\
---
name: pptx
description: "Create and edit PowerPoint presentations."
activation:
  tags:
    - pptx
    - presentation
    - slides
  patterns:
    - "\\\\.(pptx|ppt)$"
  max-context-tokens: 3000
---

# PPTX Skill

Use python-pptx for all creation tasks.
"""

DOCX_SKILL_MD = """\
---
name: docx
description: "Create and edit Word documents."
activation:
  tags:
    - docx
    - word
    - document
---

# DOCX Skill

Use python-docx for document creation.
"""

SELF_QA_SKILL_MD = """\
---
description: >-
  Automated QA testing for web applications. Systematically discovers all interactive
  elements, tests each one, audits accessibility via ARIA tree, detects visual
  regressions, and generates a structured QA report.
name: self-qa
tags:
  - qa
  - testing
  - browser
category: development
allowed-tools: browser_navigate browser_inspect browser_snapshot browser_interact browser_extract browser_manage
---

# Self QA — Automated Web Application Testing

You are a QA engineer performing systematic testing.
"""


@pytest.fixture()
def skills_storage(tmp_path):
    """Create a temporary storage with prebuilt skills."""
    prebuilt = tmp_path / "skills" / "prebuilt"

    pptx_dir = prebuilt / "pptx"
    pptx_dir.mkdir(parents=True)
    (pptx_dir / "SKILL.md").write_text(PPTX_SKILL_MD)

    docx_dir = prebuilt / "docx"
    docx_dir.mkdir(parents=True)
    (docx_dir / "SKILL.md").write_text(DOCX_SKILL_MD)

    return LocalStorageBackend(str(tmp_path))


@pytest.mark.asyncio
async def test_list_skills_returns_all(skills_storage):
    """StorageSkillBackend should list all skills under prefix."""
    backend = StorageSkillBackend(skills_storage, skills_prefix="skills/prebuilt")
    skills = await backend.list_skills()

    assert len(skills) == 2
    names = sorted(s.name for s in skills)
    assert names == ["docx", "pptx"]


@pytest.mark.asyncio
async def test_skill_metadata_parsed_correctly(skills_storage):
    """Skill metadata should be parsed from SKILL.md frontmatter."""
    backend = StorageSkillBackend(skills_storage, skills_prefix="skills/prebuilt")
    skills = await backend.list_skills()

    pptx = next(s for s in skills if s.name == "pptx")
    assert pptx.description == "Create and edit PowerPoint presentations."
    assert pptx.trust == SkillTrust.INSTALLED
    assert pptx.storage_skill_id == "pptx"
    assert pptx.is_storage_skill is True
    assert pptx.storage_path == "skills/prebuilt/pptx"
    """get_skill_content should return full SKILL.md content."""
    backend = StorageSkillBackend(skills_storage, skills_prefix="skills/prebuilt")

    content = await backend.get_skill_content("pptx")
    assert "# PPTX Skill" in content
    assert "python-pptx" in content


@pytest.mark.asyncio
async def test_load_specific_skills(skills_storage):
    """load_skills should return only requested skills."""
    backend = StorageSkillBackend(skills_storage, skills_prefix="skills/prebuilt")

    loaded = await backend.load_skills(["pptx"])
    assert len(loaded) == 1
    assert loaded[0].name == "pptx"


@pytest.mark.asyncio
async def test_empty_prefix_returns_empty(tmp_path):
    """Empty storage prefix should return empty list."""
    (tmp_path / "skills" / "empty").mkdir(parents=True)
    storage = LocalStorageBackend(str(tmp_path))
    backend = StorageSkillBackend(storage, skills_prefix="skills/empty")

    skills = await backend.list_skills()
    assert skills == []


@pytest.mark.asyncio
async def test_directory_without_skill_md_skipped(tmp_path):
    """Directories without SKILL.md should be silently skipped."""
    prebuilt = tmp_path / "skills" / "prebuilt"
    (prebuilt / "incomplete_skill").mkdir(parents=True)
    (prebuilt / "incomplete_skill" / "readme.txt").write_text("Not a skill")

    (prebuilt / "valid_skill").mkdir(parents=True)
    (prebuilt / "valid_skill" / "SKILL.md").write_text(PPTX_SKILL_MD)

    storage = LocalStorageBackend(str(tmp_path))
    backend = StorageSkillBackend(storage, skills_prefix="skills/prebuilt")

    skills = await backend.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "valid_skill"


@pytest.mark.asyncio
async def test_default_trust_installed(skills_storage):
    """Skills loaded without default_trust should have INSTALLED trust."""
    backend = StorageSkillBackend(skills_storage, skills_prefix="skills/prebuilt")
    skills = await backend.list_skills()

    for skill in skills:
        assert skill.trust == SkillTrust.INSTALLED


@pytest.mark.asyncio
async def test_default_trust_trusted(skills_storage):
    """Skills loaded with default_trust=TRUSTED should have TRUSTED trust."""
    backend = StorageSkillBackend(
        skills_storage,
        skills_prefix="skills/prebuilt",
        default_trust=SkillTrust.TRUSTED,
    )
    skills = await backend.list_skills()

    assert len(skills) == 2
    for skill in skills:
        assert skill.trust == SkillTrust.TRUSTED


@pytest.mark.asyncio
async def test_get_skill_content_not_found(skills_storage):
    """get_skill_content should raise FileNotFoundError for missing skill."""
    backend = StorageSkillBackend(skills_storage, skills_prefix="skills/prebuilt")

    with pytest.raises(FileNotFoundError):
        await backend.get_skill_content("nonexistent")


@pytest.mark.asyncio
async def test_get_skill_resources(tmp_path):
    """get_skill_resources should return resource file content."""
    prebuilt = tmp_path / "skills" / "prebuilt" / "test_skill"
    prebuilt.mkdir(parents=True)
    (prebuilt / "SKILL.md").write_text(PPTX_SKILL_MD)

    scripts_dir = prebuilt / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "helper.py").write_bytes(b"print('hello')")

    storage = LocalStorageBackend(str(tmp_path))
    backend = StorageSkillBackend(storage, skills_prefix="skills/prebuilt")

    content = await backend.get_skill_resources("test_skill", "scripts/helper.py")
    assert content == b"print('hello')"


@pytest.mark.asyncio
async def test_get_skill_resources_not_found(skills_storage):
    """get_skill_resources should raise FileNotFoundError for missing resource."""
    backend = StorageSkillBackend(skills_storage, skills_prefix="skills/prebuilt")

    with pytest.raises(FileNotFoundError):
        await backend.get_skill_resources("pptx", "nonexistent.txt")


@pytest.mark.asyncio
async def test_list_skill_resources(tmp_path):
    """list_skill_resources should return all non-SKILL.md files."""
    prebuilt = tmp_path / "skills" / "prebuilt" / "test_skill"
    prebuilt.mkdir(parents=True)
    (prebuilt / "SKILL.md").write_text(PPTX_SKILL_MD)

    scripts_dir = prebuilt / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "helper.py").write_text("print('hello')")
    (prebuilt / "LICENSE.txt").write_text("MIT")

    storage = LocalStorageBackend(str(tmp_path))
    backend = StorageSkillBackend(storage, skills_prefix="skills/prebuilt")

    resources = await backend.list_skill_resources("test_skill")
    assert "LICENSE.txt" in resources
    assert "scripts/helper.py" in resources
    assert "SKILL.md" not in [r.split("/")[-1] for r in resources]


@pytest.mark.asyncio
async def test_list_skill_resources_empty(skills_storage):
    """list_skill_resources should return empty list for nonexistent skill."""
    backend = StorageSkillBackend(skills_storage, skills_prefix="skills/prebuilt")
    resources = await backend.list_skill_resources("nonexistent")
    assert resources == []


@pytest.mark.asyncio
async def test_oversized_skill_md_skipped(tmp_path):
    """Skills with SKILL.md exceeding size limit should be skipped."""
    prebuilt = tmp_path / "skills" / "prebuilt" / "big_skill"
    prebuilt.mkdir(parents=True)
    oversized_content = "---\ndescription: test\n---\n" + "x" * (1024 * 1024 + 1)
    (prebuilt / "SKILL.md").write_text(oversized_content)

    storage = LocalStorageBackend(str(tmp_path))
    backend = StorageSkillBackend(storage, skills_prefix="skills/prebuilt")

    skills = await backend.list_skills()
    assert len(skills) == 0


@pytest.mark.asyncio
async def test_invalid_frontmatter_skipped(tmp_path):
    """Skills with invalid YAML frontmatter should be skipped."""
    prebuilt = tmp_path / "skills" / "prebuilt" / "broken_skill"
    prebuilt.mkdir(parents=True)
    (prebuilt / "SKILL.md").write_text("---\n: invalid yaml [[\n---\nContent")

    storage = LocalStorageBackend(str(tmp_path))
    backend = StorageSkillBackend(storage, skills_prefix="skills/prebuilt")

    skills = await backend.list_skills()
    assert len(skills) == 0


@pytest.mark.asyncio
async def test_load_skills_invalid_id_skipped(tmp_path):
    """load_skills should skip invalid skill IDs gracefully."""
    prebuilt = tmp_path / "skills" / "prebuilt" / "valid"
    prebuilt.mkdir(parents=True)
    (prebuilt / "SKILL.md").write_text(PPTX_SKILL_MD)

    storage = LocalStorageBackend(str(tmp_path))
    backend = StorageSkillBackend(storage, skills_prefix="skills/prebuilt")

    loaded = await backend.load_skills(["valid", "nonexistent"])
    assert len(loaded) == 1
    assert loaded[0].name == "valid"


@pytest.mark.asyncio
async def test_self_qa_skill_loaded_with_allowed_tools(tmp_path):
    """self-qa style SKILL.md with allowed-tools and tags should load correctly."""
    qa_dir = tmp_path / "skills" / "prebuilt" / "self-qa"
    qa_dir.mkdir(parents=True)
    (qa_dir / "SKILL.md").write_text(SELF_QA_SKILL_MD)

    storage = LocalStorageBackend(str(tmp_path))
    backend = StorageSkillBackend(
        storage, skills_prefix="skills/prebuilt", default_trust=SkillTrust.TRUSTED
    )

    skills = await backend.list_skills()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "self-qa"
    assert "Automated QA testing" in skill.description
    assert skill.trust == SkillTrust.TRUSTED
    assert skill.allowed_tools == [
        "browser_navigate", "browser_inspect", "browser_snapshot",
        "browser_interact", "browser_extract", "browser_manage",
    ]

    content = await backend.get_skill_content("self-qa")
    assert "# Self QA" in content
    assert "QA engineer" in content



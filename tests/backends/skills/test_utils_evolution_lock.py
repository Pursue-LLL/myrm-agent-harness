"""Unit tests for evolution lock utilities in SKILL.md frontmatter."""

from pathlib import Path

from myrm_agent_harness.backends.skills._utils import update_frontmatter_evolution_lock


def test_update_frontmatter_evolution_lock_adds_new(tmp_path: Path):
    """Test adding evolution_locked to a file without it."""
    content = "---\nname: test\n---\nHello"
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(content)

    update_frontmatter_evolution_lock(skill_file, True)

    updated = skill_file.read_text()
    assert "evolution_locked: true" in updated
    assert "---\nname: test\nevolution_locked: true\n\n---\nHello" in updated


def test_update_frontmatter_evolution_lock_updates_existing(tmp_path: Path):
    """Test updating existing evolution_locked."""
    content = "---\nname: test\nevolution_locked: false\nversion: 1\n---\nHello"
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(content)

    update_frontmatter_evolution_lock(skill_file, True)

    updated = skill_file.read_text()
    assert "evolution_locked: true" in updated
    assert "evolution_locked: false" not in updated
    assert "version: 1" in updated


def test_update_frontmatter_evolution_lock_handles_dash(tmp_path: Path):
    """Test updating evolution-locked with a dash."""
    content = "---\nname: test\nevolution-locked: true\n---\nHello"
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(content)

    update_frontmatter_evolution_lock(skill_file, False)

    updated = skill_file.read_text()
    assert "evolution-locked: false" in updated
    assert "evolution-locked: true" not in updated


def test_update_frontmatter_evolution_lock_handles_yes(tmp_path: Path):
    """Test updating evolution_locked when value is 'yes'."""
    content = "---\nname: test\nevolution_locked: yes\n---\nHello"
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(content)

    update_frontmatter_evolution_lock(skill_file, False)

    updated = skill_file.read_text()
    assert "evolution_locked: false" in updated
    assert "evolution_locked: yes" not in updated
    # Verify no duplicate keys
    assert updated.count("evolution_locked") == 1


def test_update_frontmatter_evolution_lock_nonexistent_file(tmp_path: Path):
    """Test updating a non-existent file doesn't crash."""
    skill_file = tmp_path / "nonexistent.md"
    # Should just return without error
    update_frontmatter_evolution_lock(skill_file, True)


def test_update_frontmatter_evolution_lock_no_frontmatter(tmp_path: Path):
    """Test updating a file with no valid frontmatter doesn't crash."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("Just some text")
    # Should just log warning and return
    update_frontmatter_evolution_lock(skill_file, True)
    assert skill_file.read_text() == "Just some text"

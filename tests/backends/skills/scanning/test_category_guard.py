"""Unit tests for category bucket collision and junction/symlink shield (Item 103).

[INPUT]
- myrm_agent_harness.backends.skills.scanning.category_guard

[OUTPUT]
- Pytest suite covering is_path_redirect, is_category_bucket, and validate_safe_install_target.

[POS]
myrm-agent-harness/tests/backends/skills/scanning/test_category_guard.py
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from myrm_agent_harness.backends.skills.scanning.category_guard import (
    CategoryBucketCollisionError,
    PathRedirectionError,
    is_category_bucket,
    is_path_redirect,
    validate_safe_install_target,
)


def test_is_category_bucket_detection(tmp_path: Path) -> None:
    # 1. Non-existent path
    non_existent = tmp_path / "does_not_exist"
    is_bucket, skills = is_category_bucket(non_existent)
    assert not is_bucket
    assert skills == []

    # 2. Standalone skill directory (has top-level SKILL.md)
    standalone = tmp_path / "my-skill"
    standalone.mkdir()
    (standalone / "SKILL.md").write_text("# My Skill", encoding="utf-8")
    is_bucket, skills = is_category_bucket(standalone)
    assert not is_bucket
    assert skills == []

    # 3. Category bucket directory (no top-level SKILL.md, but contains child skills)
    category_bucket = tmp_path / "frontend"
    category_bucket.mkdir()
    child1 = category_bucket / "react-helper"
    child1.mkdir()
    (child1 / "SKILL.md").write_text("# React Helper", encoding="utf-8")

    child2 = category_bucket / "vue-helper"
    child2.mkdir()
    (child2 / "SKILL.md").write_text("# Vue Helper", encoding="utf-8")

    is_bucket, skills = is_category_bucket(category_bucket)
    assert is_bucket
    assert set(skills) == {"react-helper", "vue-helper"}


def test_validate_safe_install_target_blocks_category_bucket(tmp_path: Path) -> None:
    category_bucket = tmp_path / "nlp"
    category_bucket.mkdir()
    sub_skill = category_bucket / "sentiment"
    sub_skill.mkdir()
    (sub_skill / "SKILL.md").write_text("# Sentiment Analysis", encoding="utf-8")

    with pytest.raises(CategoryBucketCollisionError) as exc_info:
        validate_safe_install_target(category_bucket)

    assert "Refusing to overwrite category bucket 'nlp'" in str(exc_info.value)
    assert "sentiment" in str(exc_info.value)


def test_validate_safe_install_target_blocks_symlinks(tmp_path: Path) -> None:
    real_dir = tmp_path / "real_skill"
    real_dir.mkdir()
    (real_dir / "SKILL.md").write_text("# Real Skill", encoding="utf-8")

    symlink_dir = tmp_path / "symlink_skill"
    try:
        os.symlink(real_dir, symlink_dir)
    except OSError:
        pytest.skip("Symlinks not supported on this filesystem/OS")

    assert is_path_redirect(symlink_dir)

    with pytest.raises(PathRedirectionError) as exc_info:
        validate_safe_install_target(symlink_dir)

    assert "symlink" in str(exc_info.value).lower()


def test_validate_safe_install_target_blocks_root_escape(tmp_path: Path) -> None:
    install_root = tmp_path / "skills"
    install_root.mkdir()

    outside_target = tmp_path / "other_dir" / "rogue_skill"

    with pytest.raises(PathRedirectionError) as exc_info:
        validate_safe_install_target(outside_target, base_install_root=install_root)

    assert "escapes installation root" in str(exc_info.value)


def test_validate_safe_install_target_passes_for_clean_target(tmp_path: Path) -> None:
    install_root = tmp_path / "skills"
    install_root.mkdir()

    clean_target = install_root / "new_skill"
    validate_safe_install_target(clean_target, base_install_root=install_root)

    # Also passes if it is an existing standalone skill being upgraded
    clean_target.mkdir()
    (clean_target / "SKILL.md").write_text("# Version 1", encoding="utf-8")
    validate_safe_install_target(clean_target, base_install_root=install_root)

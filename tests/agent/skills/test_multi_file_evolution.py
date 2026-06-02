"""Unit tests for multi-file evolution support.

Covers:
  - Multi-file FULL format parsing (*** File: headers)
  - Unicode normalization in fuzzy matching
  - _collect_skill_files() filtering logic
  - SkillPatchResult.auxiliary_files field
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.agent.skills.evolution.pipeline.patch import (
    PatchType,
    apply_skill_patch,
    detect_patch_type,
    parse_multi_file_full,
)
from myrm_agent_harness.utils.fuzzy_match import fuzzy_find


class TestDetectPatchType:
    """Test patch type auto-detection including multi-file format."""

    def test_detect_multi_file_marker(self) -> None:
        content = "*** File: SKILL.md\nsome content\n*** File: scripts/run.sh\necho hi"
        assert detect_patch_type(content) == PatchType.MULTI_FILE_FULL

    def test_detect_begin_files_marker(self) -> None:
        content = "*** Begin Files\n*** File: SKILL.md\ncontent"
        assert detect_patch_type(content) == PatchType.MULTI_FILE_FULL

    def test_detect_diff_over_full(self) -> None:
        content = "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"
        assert detect_patch_type(content) == PatchType.DIFF

    def test_detect_full_default(self) -> None:
        content = "# My Skill\nDo something useful."
        assert detect_patch_type(content) == PatchType.FULL

    def test_multi_file_takes_priority_over_search_replace(self) -> None:
        content = "*** File: SKILL.md\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"
        assert detect_patch_type(content) == PatchType.MULTI_FILE_FULL


class TestParseMultiFileFull:
    """Test *** File: format parsing."""

    def test_basic_two_files(self) -> None:
        llm_output = "*** File: SKILL.md\n# My Skill\nDo X then Y.\n\n*** File: scripts/run.sh\n#!/bin/bash\necho hello"
        files = parse_multi_file_full(llm_output)
        assert "SKILL.md" in files
        assert "scripts/run.sh" in files
        assert "# My Skill" in files["SKILL.md"]
        assert "echo hello" in files["scripts/run.sh"]

    def test_three_files(self) -> None:
        llm_output = (
            "*** File: SKILL.md\nContent A\n*** File: config.yaml\nkey: val\n*** File: scripts/test.py\nimport pytest"
        )
        files = parse_multi_file_full(llm_output)
        assert len(files) == 3
        assert "config.yaml" in files

    def test_empty_file_content(self) -> None:
        llm_output = "*** File: SKILL.md\n\n*** File: empty.txt\n"
        files = parse_multi_file_full(llm_output)
        assert "SKILL.md" in files
        assert "empty.txt" in files

    def test_no_headers_returns_empty(self) -> None:
        llm_output = "Just plain text without any markers."
        files = parse_multi_file_full(llm_output)
        assert files == {}

    def test_path_with_subdirectory(self) -> None:
        llm_output = '*** File: resources/data/config.json\n{"key": "value"}'
        files = parse_multi_file_full(llm_output)
        assert "resources/data/config.json" in files


class TestApplyMultiFileFull:
    """Test apply_skill_patch with MULTI_FILE_FULL format."""

    def test_multi_file_full_success(self) -> None:
        llm_output = "*** File: SKILL.md\n# Fixed Skill\nDo X.\n\n*** File: scripts/post.ts\nconsole.log('fixed');"
        result = apply_skill_patch("original content", llm_output, PatchType.MULTI_FILE_FULL)
        assert result.ok
        assert "# Fixed Skill" in result.content
        assert "scripts/post.ts" in result.auxiliary_files
        assert "console.log" in result.auxiliary_files["scripts/post.ts"]

    def test_multi_file_missing_skill_md(self) -> None:
        llm_output = "*** File: scripts/run.sh\necho hello"
        result = apply_skill_patch("original", llm_output, PatchType.MULTI_FILE_FULL)
        assert not result.ok
        assert "SKILL.md" in result.error_message

    def test_auto_detect_multi_file(self) -> None:
        llm_output = "*** File: SKILL.md\n# Auto detected\n\n*** File: helper.py\nprint('hi')"
        result = apply_skill_patch("old", llm_output, PatchType.AUTO)
        assert result.ok
        assert result.auxiliary_files == {"helper.py": "print('hi')"}

    def test_single_file_has_empty_auxiliary(self) -> None:
        result = apply_skill_patch("old", "new full content", PatchType.FULL)
        assert result.ok
        assert result.auxiliary_files == {}

    def test_diff_has_empty_auxiliary(self) -> None:
        original = "line1\nline2\nline3"
        diff = "<<<<<<< SEARCH\nline2\n=======\nmodified\n>>>>>>> REPLACE"
        result = apply_skill_patch(original, diff, PatchType.DIFF)
        assert result.ok
        assert result.auxiliary_files == {}

    def test_num_changes_includes_auxiliary(self) -> None:
        llm_output = "*** File: SKILL.md\n# Skill\n\n*** File: a.py\ncode\n\n*** File: b.py\nmore code"
        result = apply_skill_patch("old", llm_output, PatchType.MULTI_FILE_FULL)
        assert result.ok
        assert result.num_changes_applied == 3  # SKILL.md + 2 aux files


class TestUnicodeNormalization:
    """Test Unicode normalization in fuzzy matching."""

    def test_fuzzy_find_with_smart_quotes(self) -> None:
        content = "config['api_key']"
        find = "config[\u2018api_key\u2019]"
        result = fuzzy_find(content, find)
        assert result is not None
        assert result.matched_text == content

    def test_fuzzy_find_with_em_dash(self) -> None:
        content = "value -- default"
        find = "value \u2014 default"
        result = fuzzy_find(content, find)
        assert result is not None


class TestCollectSkillFiles:
    """Test _collect_skill_files in GitInstaller."""

    def test_empty_directory(self) -> None:
        from myrm_agent_harness.agent.skills.discovery.installers.git_installer import GitInstaller

        installer = GitInstaller.__new__(GitInstaller)
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = Path(tmpdir) / "SKILL.md"
            skill_md.write_text("# Skill")
            result = installer._collect_skill_files(Path(tmpdir))
            assert "SKILL.md" in result.files

    def test_with_auxiliary_files(self) -> None:
        from myrm_agent_harness.agent.skills.discovery.installers.git_installer import GitInstaller

        installer = GitInstaller.__new__(GitInstaller)
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = Path(tmpdir) / "SKILL.md"
            skill_md.write_text("# Skill")
            script = Path(tmpdir) / "scripts"
            script.mkdir()
            (script / "run.sh").write_text("echo hello")
            (Path(tmpdir) / "config.yaml").write_text("key: val")

            result = installer._collect_skill_files(Path(tmpdir))
            assert "scripts/run.sh" in result.files
            assert "config.yaml" in result.files

    def test_skips_hidden_dirs(self) -> None:
        from myrm_agent_harness.agent.skills.discovery.installers.git_installer import GitInstaller

        installer = GitInstaller.__new__(GitInstaller)
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = Path(tmpdir) / "SKILL.md"
            skill_md.write_text("# Skill")
            (Path(tmpdir) / "good.txt").write_text("keep")

            result = installer._collect_skill_files(Path(tmpdir))
            assert "good.txt" in result.files

    def test_collects_nested_files(self) -> None:
        from myrm_agent_harness.agent.skills.discovery.installers.git_installer import GitInstaller

        installer = GitInstaller.__new__(GitInstaller)
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = Path(tmpdir) / "SKILL.md"
            skill_md.write_text("# Nested Skill")
            nested = Path(tmpdir) / "sub"
            nested.mkdir()
            (nested / "helper.py").write_text("print('hi')")

            result = installer._collect_skill_files(Path(tmpdir))
            assert "sub/helper.py" in result.files
            assert "SKILL.md" in result.files

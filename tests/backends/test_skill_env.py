"""Tests for skill environment variable injection system.

Covers:
- resolve_skill_env(): per-skill env resolution with apiKey→primaryEnv mapping
- extract_skill_name(), rewrite_skill_paths(), detect_skill_script_command()
- prepare_skill_env()
- parse_skill_frontmatter(): primary_env field parsing
- build_skill_metadata(): primary_env propagation to SkillMetadata
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.agent.skills.runtime.env import (
    detect_skill_script_command,
    extract_skill_name,
    prepare_skill_env,
    resolve_skill_env,
    rewrite_skill_paths,
)
from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter
from myrm_agent_harness.backends.skills.types import SkillTrust

# ── resolve_skill_env() ──────────────────────────────────────────────────


class TestResolveSkillEnv:
    def test_empty_config_returns_empty(self) -> None:
        assert resolve_skill_env("s1", "SOME_KEY", None) == {}
        assert resolve_skill_env("s1", "SOME_KEY", {}) == {}

    def test_custom_env_vars_passed_through(self) -> None:
        result = resolve_skill_env("s1", None, {"FOO": "bar", "BAZ": "qux"})
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_api_key_mapped_to_primary_env(self) -> None:
        result = resolve_skill_env("s1", "BRAVE_API_KEY", {"api_key": "sk-123"})
        assert result == {"BRAVE_API_KEY": "sk-123"}

    def test_api_key_ignored_without_primary_env(self) -> None:
        result = resolve_skill_env("s1", None, {"api_key": "sk-123"})
        assert result == {}

    def test_api_key_ignored_when_empty(self) -> None:
        result = resolve_skill_env("s1", "BRAVE_API_KEY", {"api_key": ""})
        assert result == {}

    def test_mixed_api_key_and_custom_vars(self) -> None:
        result = resolve_skill_env(
            "s1",
            "BRAVE_API_KEY",
            {"api_key": "sk-123", "CUSTOM_VAR": "val", "ANOTHER": "v2"},
        )
        assert result == {"BRAVE_API_KEY": "sk-123", "CUSTOM_VAR": "val", "ANOTHER": "v2"}

    def test_empty_values_filtered(self) -> None:
        result = resolve_skill_env("s1", None, {"EMPTY": "", "VALID": "ok"})
        assert result == {"VALID": "ok"}

    def test_api_key_not_included_as_raw_key(self) -> None:
        """api_key should only be mapped via primary_env, never injected as 'api_key'."""
        result = resolve_skill_env("s1", "MY_KEY", {"api_key": "secret", "OTHER": "v"})
        assert "api_key" not in result
        assert result["MY_KEY"] == "secret"


# ── extract_skill_name() ─────────────────────────────────────────────────


class TestExtractSkillName:
    def test_basic_path(self) -> None:
        assert extract_skill_name("/path/to/skills/web_scraper") == "web_scraper"

    def test_trailing_slash_stripped(self) -> None:
        assert extract_skill_name("/path/to/skills/web_scraper/") == "web_scraper"

    def test_simple_name(self) -> None:
        assert extract_skill_name("my-skill") == "my-skill"


# ── rewrite_skill_paths() ────────────────────────────────────────────────


class TestRewriteSkillPaths:
    def test_no_skill_path_unchanged(self) -> None:
        cmd = "python3 scripts/run.py"
        result, name = rewrite_skill_paths(cmd)
        assert result == cmd
        assert name is None

    def test_single_skill_path_rewritten(self) -> None:
        cmd = "python3 .claude/skills/my-tool/scripts/run.py"
        result, name = rewrite_skill_paths(cmd)
        assert result == "python3 scripts/run.py"
        assert name == "my-tool"

    def test_multiple_same_skill_paths(self) -> None:
        cmd = "python3 .claude/skills/tool/a.py .claude/skills/tool/b.py"
        result, name = rewrite_skill_paths(cmd)
        assert "a.py" in result
        assert "b.py" in result
        assert ".claude/skills" not in result
        assert name == "tool"


# ── detect_skill_script_command() ────────────────────────────────────────


class TestDetectSkillScriptCommand:
    def test_skill_path_detected(self) -> None:
        detected, name = detect_skill_script_command("python3 .claude/skills/my-tool/run.py")
        assert detected is True
        assert name == "my-tool"

    def test_no_skill_path(self) -> None:
        detected, name = detect_skill_script_command("echo hello")
        assert detected is False
        assert name is None

    def test_hyphenated_skill_name(self) -> None:
        detected, name = detect_skill_script_command(
            "python3 .claude/skills/google-workspace/scripts/google_api.py calendar-today"
        )
        assert detected is True
        assert name == "google-workspace"


# ── prepare_skill_env() ──────────────────────────────────────────────────


class TestPrepareSkillEnv:
    def test_basic(self, tmp_path: Path) -> None:
        result = prepare_skill_env(tmp_path, "/store/prebuilt/web-tool", "web-tool")
        assert result["PYTHONPATH"] == str(tmp_path / "skills" / "web-tool")
        assert result["working_dir"] == str(tmp_path / "skills" / "web-tool")

    def test_auto_extract_name(self, tmp_path: Path) -> None:
        result = prepare_skill_env(tmp_path, "/store/prebuilt/auto-skill")
        assert "auto-skill" in result["PYTHONPATH"]


# ── parse_skill_frontmatter() primary_env ────────────────────────────────


class TestFrontmatterPrimaryEnv:
    def test_camel_case_primary_env(self) -> None:
        content = "---\ndescription: test\nprimaryEnv: BRAVE_API_KEY\n---\n# Skill\n"
        fm = parse_skill_frontmatter(content, "test")
        assert fm.primary_env == "BRAVE_API_KEY"

    def test_snake_case_primary_env(self) -> None:
        content = "---\ndescription: test\nprimary_env: OPENAI_API_KEY\n---\n# Skill\n"
        fm = parse_skill_frontmatter(content, "test")
        assert fm.primary_env == "OPENAI_API_KEY"

    def test_no_primary_env_defaults_to_none(self) -> None:
        content = "---\ndescription: test\n---\n# Skill\n"
        fm = parse_skill_frontmatter(content, "test")
        assert fm.primary_env is None

    def test_empty_primary_env_treated_as_none(self) -> None:
        content = '---\ndescription: test\nprimaryEnv: ""\n---\n# Skill\n'
        fm = parse_skill_frontmatter(content, "test")
        assert fm.primary_env is None

    def test_whitespace_only_primary_env_treated_as_none(self) -> None:
        content = "---\ndescription: test\nprimaryEnv: '   '\n---\n# Skill\n"
        fm = parse_skill_frontmatter(content, "test")
        assert fm.primary_env is None


# ── build_skill_metadata() primary_env propagation ───────────────────────


class TestBuildSkillMetadataPrimaryEnv:
    def test_primary_env_propagated(self) -> None:
        content = "---\ndescription: test\nprimaryEnv: SOME_KEY\n---\n# Skill\n"
        fm = parse_skill_frontmatter(content, "my-skill")
        meta = build_skill_metadata(
            skill_name="my-skill",
            frontmatter=fm,
            storage_path="/tmp/skills/my-skill",
            content=content,
            trust=SkillTrust.INSTALLED,
        )
        assert meta.primary_env == "SOME_KEY"

    def test_no_primary_env_propagated_as_none(self) -> None:
        content = "---\ndescription: test\n---\n# Skill\n"
        fm = parse_skill_frontmatter(content, "my-skill")
        meta = build_skill_metadata(
            skill_name="my-skill",
            frontmatter=fm,
            storage_path="/tmp/skills/my-skill",
            content=content,
            trust=SkillTrust.INSTALLED,
        )
        assert meta.primary_env is None

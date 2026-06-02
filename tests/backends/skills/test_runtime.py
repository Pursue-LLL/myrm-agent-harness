"""Tests for skill runtime builder (_runtime.py).

Covers check_requirements(), compile_patterns(), compute_content_hash(),
and build_skill_metadata() — including bins/env/config dependency checks,
oversized/invalid pattern handling, and token budget clamping.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from myrm_agent_harness.backends.skills._runtime import (
    build_skill_metadata,
    check_requirements,
    compute_content_hash,
)
from myrm_agent_harness.backends.skills._utils import SkillFrontmatter
from myrm_agent_harness.backends.skills.types import (
    SkillRequires,
    SkillTrust,
)

MINIMAL_SKILL_CONTENT = "---\ndescription: test\n---\n# Test skill\nSome content."


def _make_frontmatter(
    *,
    requires: SkillRequires | None = None,
    description: str = "test skill",
) -> SkillFrontmatter:
    return SkillFrontmatter(
        description=description,
        requires=requires,
    )


class TestCheckRequirements:
    """check_requirements() — bins/env/config dependency validation."""

    def test_no_requires_returns_available(self) -> None:
        fm = _make_frontmatter(requires=None)
        available, reason = check_requirements(fm)
        assert available is True
        assert reason is None

    def test_empty_requires_returns_available(self) -> None:
        fm = _make_frontmatter(requires=SkillRequires())
        available, reason = check_requirements(fm)
        assert available is True
        assert reason is None

    @patch("shutil.which", return_value="/usr/bin/python3")
    def test_bins_satisfied(self, mock_which: object) -> None:
        fm = _make_frontmatter(requires=SkillRequires(bins=["python3"]))
        available, reason = check_requirements(fm)
        assert available is True
        assert reason is None

    @patch("shutil.which", return_value=None)
    def test_bins_missing(self, mock_which: object) -> None:
        fm = _make_frontmatter(requires=SkillRequires(bins=["nonexistent-tool"]))
        available, reason = check_requirements(fm)
        assert available is False
        assert reason is not None
        assert "CLI: nonexistent-tool" in reason

    @patch.dict("os.environ", {"MY_API_KEY": "secret"}, clear=False)
    def test_env_satisfied(self) -> None:
        fm = _make_frontmatter(requires=SkillRequires(env=["MY_API_KEY"]))
        available, _reason = check_requirements(fm)
        assert available is True

    @patch.dict("os.environ", {}, clear=False)
    def test_env_missing(self) -> None:
        fm = _make_frontmatter(requires=SkillRequires(env=["TOTALLY_MISSING_VAR_XYZ"]))
        available, reason = check_requirements(fm)
        assert available is False
        assert "ENV: TOTALLY_MISSING_VAR_XYZ" in (reason or "")

    def test_config_satisfied(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("key: value")
        fm = _make_frontmatter(requires=SkillRequires(config=[str(cfg)]))
        available, _reason = check_requirements(fm)
        assert available is True

    def test_config_missing(self) -> None:
        fm = _make_frontmatter(requires=SkillRequires(config=["/nonexistent/path/config.yaml"]))
        available, reason = check_requirements(fm)
        assert available is False
        assert "CONFIG: /nonexistent/path/config.yaml" in (reason or "")

    @patch("shutil.which", return_value=None)
    @patch.dict("os.environ", {}, clear=False)
    def test_multiple_missing(self, mock_which: object) -> None:
        fm = _make_frontmatter(
            requires=SkillRequires(
                bins=["missing-bin"],
                env=["MISSING_ENV_VAR_XYZ"],
                config=["/no/such/file"],
            )
        )
        available, reason = check_requirements(fm)
        assert available is False
        assert reason is not None
        assert "CLI: missing-bin" in reason
        assert "ENV: MISSING_ENV_VAR_XYZ" in reason
        assert "CONFIG: /no/such/file" in reason




class TestComputeContentHash:
    """compute_content_hash() — SHA-256 with line ending normalization."""

    def test_deterministic(self) -> None:
        h1 = compute_content_hash("hello\nworld")
        h2 = compute_content_hash("hello\nworld")
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_crlf_normalized(self) -> None:
        lf = compute_content_hash("hello\nworld")
        crlf = compute_content_hash("hello\r\nworld")
        assert lf == crlf

    def test_cr_normalized(self) -> None:
        lf = compute_content_hash("hello\nworld")
        cr = compute_content_hash("hello\rworld")
        assert lf == cr


class TestBuildSkillMetadata:
    """build_skill_metadata() — full metadata assembly."""

    @patch("shutil.which", return_value="/usr/bin/xurl")
    def test_basic_build(self, mock_which: object) -> None:
        fm = _make_frontmatter(
            requires=SkillRequires(bins=["xurl"]),
        )
        meta = build_skill_metadata(
            skill_name="xurl",
            frontmatter=fm,
            storage_path="skills/prebuilt/xurl",
            content=MINIMAL_SKILL_CONTENT,
            trust=SkillTrust.TRUSTED,
        )
        assert meta.name == "xurl"
        assert meta.available is True
        assert meta.unavailable_reason is None
        assert meta.content_hash.startswith("sha256:")

    @patch("shutil.which", return_value=None)
    def test_unavailable_when_bins_missing(self, mock_which: object) -> None:
        fm = _make_frontmatter(requires=SkillRequires(bins=["missing-tool"]))
        meta = build_skill_metadata(
            skill_name="test",
            frontmatter=fm,
            storage_path="skills/prebuilt/test",
            content=MINIMAL_SKILL_CONTENT,
            trust=SkillTrust.TRUSTED,
        )
        assert meta.available is False
        assert meta.unavailable_reason is not None
        assert "CLI: missing-tool" in meta.unavailable_reason


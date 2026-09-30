"""Unit tests for the git and zip skill installers.

[INPUT]
- myrm_agent_harness.agent.skills.market.installers

[OUTPUT]
- pytest suite covering skill directory resolution, file collection,
  frontmatter parsing, and clone/extract failure paths. The git clone
  itself is stubbed, so no network or subprocess runs.

[POS]
myrm-agent-harness/tests/agent/skills/market/installers/test_installers.py
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.skills.market.installers.git_installer import (
    GitInstaller,
    _find_skill_md,
    _parse_skill_md_metadata,
    _walk_skill_dir,
)
from myrm_agent_harness.agent.skills.market.installers.zip_installer import (
    MAX_ZIP_SIZE,
    ZIP_DOWNLOAD_TIMEOUT,
    ZipInstaller,
    _is_excluded_file,
)

SKILL_MD = b"---\nname: Alpha\ndescription: does alpha\n---\n# Alpha\n"


def _make_skill(root: Path, rel: str, *, name: str = "Alpha", body: bytes = b"") -> Path:
    skill_dir = root / rel
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_bytes(f"---\nname: {name}\ndescription: d\n---\n# body\n".encode())
    if body:
        (skill_dir / "data.txt").write_bytes(body)
    return skill_dir


class TestResolveSkillDir:
    def test_no_subdirectory_returns_root(self, tmp_path: Path) -> None:
        assert GitInstaller._resolve_skill_dir(tmp_path, None) == tmp_path

    def test_exact_path_wins(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "skills/pdf")
        assert GitInstaller._resolve_skill_dir(tmp_path, "skills/pdf") == tmp_path / "skills/pdf"

    def test_matches_by_directory_name(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "nested/deep/pdf")
        assert GitInstaller._resolve_skill_dir(tmp_path, "pdf") == tmp_path / "nested" / "deep" / "pdf"

    def test_matches_by_substring(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "skills/pdf-tools")
        assert GitInstaller._resolve_skill_dir(tmp_path, "pdf") == tmp_path / "skills" / "pdf-tools"

    def test_single_candidate_is_used(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "whatever/other")
        assert GitInstaller._resolve_skill_dir(tmp_path, "absent") == tmp_path / "whatever" / "other"

    def test_existing_dir_without_skill_md(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        _make_skill(tmp_path, "a/first")
        _make_skill(tmp_path, "b/second")
        assert GitInstaller._resolve_skill_dir(tmp_path, "empty") == tmp_path / "empty"

    def test_falls_back_to_root_without_candidates(self, tmp_path: Path) -> None:
        assert GitInstaller._resolve_skill_dir(tmp_path, "absent") == tmp_path

    def test_ignores_git_internal_candidates(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "SKILL.md").write_bytes(SKILL_MD)
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "SKILL.md").write_bytes(SKILL_MD)
        # .git 内的候选被排除后只剩 real，走单候选回退
        assert GitInstaller._resolve_skill_dir(tmp_path, "zzz") == tmp_path / "real"


class TestCollectSkillFiles:
    def test_collects_files_and_metadata(self, tmp_path: Path) -> None:
        skill_dir = _make_skill(tmp_path, "pdf", body=b"payload")
        result = GitInstaller()._collect_skill_files(skill_dir)
        assert result.name == "Alpha"
        assert result.description == "d"
        assert set(result.files) == {"SKILL.md", "data.txt"}
        assert result.files["data.txt"] == b"payload"

    def test_falls_back_to_searched_skill_md(self, tmp_path: Path) -> None:
        wrapper = tmp_path / "wrapper"
        inner = wrapper / "inner"
        inner.mkdir(parents=True)
        (inner / "SKILL.md").write_bytes(SKILL_MD)
        (wrapper / "readme.md").write_bytes(b"ignored")

        result = GitInstaller()._collect_skill_files(wrapper)

        assert result.name == "Alpha"
        assert set(result.files) == {"SKILL.md"}

    def test_missing_skill_md_raises(self, tmp_path: Path) -> None:
        (tmp_path / "nothing").mkdir()
        with pytest.raises(ValueError, match=r"SKILL\.md not found"):
            GitInstaller()._collect_skill_files(tmp_path / "nothing")

    def test_missing_frontmatter_falls_back_to_dir_name(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "plain"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_bytes(b"no frontmatter here")
        (skill_dir / "file.txt").write_bytes(b"x")
        result = GitInstaller()._collect_skill_files(skill_dir)
        # SKILL.md 存在但无 frontmatter：名称回退为占位符
        assert result.name == "unnamed_skill"
        assert result.description == ""


class TestWalkHelpers:
    def test_excludes_hidden_and_junk_dirs(self, tmp_path: Path) -> None:
        for rel in (".hidden/x.txt", "node_modules/y.txt", "ok.txt", ".git/z.txt", "__pycache__/w.txt"):
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

        names = {p.name for p in _walk_skill_dir(tmp_path)}

        assert names == {"ok.txt"}

    def test_find_skill_md_respects_depth(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "SKILL.md").write_bytes(SKILL_MD)
        assert _find_skill_md(tmp_path) is None
        assert _find_skill_md(tmp_path, max_depth=6) == deep / "SKILL.md"

    def test_find_skill_md_at_depth_zero(self, tmp_path: Path) -> None:
        assert _find_skill_md(tmp_path, max_depth=0) is None

    def test_find_skill_md_skips_hidden_dirs(self, tmp_path: Path) -> None:
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "SKILL.md").write_bytes(SKILL_MD)
        assert _find_skill_md(tmp_path) is None

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            (SKILL_MD, ("Alpha", "does alpha")),
            (b"no frontmatter", ("unnamed_skill", "")),
            (b"---\nbroken: [\n---\nbody", ("unnamed_skill", "")),
            (b"---\n- a\n- b\n---\nbody", ("unnamed_skill", "")),
        ],
    )
    def test_parse_skill_md_metadata(self, content: bytes, expected: tuple[str, str]) -> None:
        assert _parse_skill_md_metadata(content) == expected


class TestGitInstallerDownload:
    @pytest.mark.asyncio
    async def test_download_cleans_temp_dir(self, tmp_path: Path) -> None:
        installer = GitInstaller()
        seen: dict[str, Path] = {}

        async def _fake_clone(_self: object, url: str, target: Path, *, ref: str | None = None) -> None:
            seen["target"] = target
            _make_skill(target, "skills/pdf", body=b"data")

        with (
            patch.object(GitInstaller, "_git_clone", new=_fake_clone),
            patch("myrm_agent_harness.agent.skills.market.installers.git_installer.shutil.rmtree") as rmtree,
        ):
            result = await installer.download("https://example.invalid/x.git", "skills/pdf")

        assert rmtree.called
        assert result.files["data.txt"] == b"data"

    @pytest.mark.asyncio
    async def test_clone_failure_propagates_and_cleans(self) -> None:
        installer = GitInstaller()
        with (
            patch.object(
                GitInstaller,
                "_git_clone",
                new=AsyncMock(side_effect=ValueError("Git clone failed: nope")),
            ),
            patch("myrm_agent_harness.agent.skills.market.installers.git_installer.shutil.rmtree") as rmtree,
            pytest.raises(ValueError, match="Git clone failed"),
        ):
            await installer.download("https://example.invalid/x.git")

        assert rmtree.called

    @pytest.mark.asyncio
    async def test_clone_timeout_reports_url(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError)
        proc.returncode = None

        with (
            patch(
                "myrm_agent_harness.agent.skills.market.installers.git_installer.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc),
            ),
            pytest.raises(ValueError, match="timed out after 60s"),
        ):
            await GitInstaller()._git_clone("https://example.invalid/x.git", tmp_path)

        assert proc.kill.called

    @pytest.mark.asyncio
    async def test_clone_reports_stderr(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b"permission denied"))
        proc.returncode = 128

        with (
            patch(
                "myrm_agent_harness.agent.skills.market.installers.git_installer.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc),
            ),
            pytest.raises(ValueError, match="permission denied"),
        ):
            await GitInstaller()._git_clone("https://example.invalid/x.git", tmp_path)

    @pytest.mark.asyncio
    async def test_clone_includes_branch_flag(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0

        with patch(
            "myrm_agent_harness.agent.skills.market.installers.git_installer.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ) as spawn:
            await GitInstaller()._git_clone("https://example.invalid/x.git", tmp_path, ref="dev")

        assert "--branch" in spawn.await_args.args
        assert "dev" in spawn.await_args.args


class TestZipExclusion:
    @pytest.mark.parametrize(
        "path",
        ["a/.git/b.txt", "a/node_modules/b.txt", "a/.venv/b.txt", "a/__pycache__/b.txt", ".hidden/b.txt"],
    )
    def test_excluded_paths(self, path: str) -> None:
        assert _is_excluded_file(path) is True

    def test_regular_path_included(self) -> None:
        assert _is_excluded_file("skills/pdf/SKILL.md") is False


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class TestZipInstaller:
    @pytest.mark.asyncio
    async def test_extracts_skill_at_root(self) -> None:
        payload = _zip_bytes({"SKILL.md": SKILL_MD, "data.txt": b"payload"})
        result = ZipInstaller()._extract_skill(payload, None)
        assert result.name == "Alpha"
        assert result.files["data.txt"] == b"payload"

    @pytest.mark.asyncio
    async def test_honours_subdirectory(self) -> None:
        # strip_top_dir 会剥掉首个路径段，故顶层目录为 archive-root
        payload = _zip_bytes({"archive-root/skills/pdf/SKILL.md": SKILL_MD})
        result = ZipInstaller()._extract_skill(payload, "skills/pdf/")
        assert set(result.files) == {"SKILL.md"}

    @pytest.mark.asyncio
    async def test_reads_plugin_manifest(self) -> None:
        import json

        payload = _zip_bytes({"plugin.json": json.dumps({"name": "suite", "description": "d"}).encode()})
        result = ZipInstaller()._extract_skill(payload, None)
        assert result.name == "suite"
        assert result.description == "d"

    @pytest.mark.asyncio
    async def test_malformed_plugin_manifest_falls_back(self) -> None:
        payload = _zip_bytes({"plugin.json": b"{not json", "SKILL.md": SKILL_MD})
        result = ZipInstaller()._extract_skill(payload, None)
        assert result.name == "Alpha"

    @pytest.mark.asyncio
    async def test_selects_shallowest_skill_root(self) -> None:
        # strip_top_dir 会剥掉统一的顶层目录，此处两个候选深度不同
        payload = _zip_bytes(
            {
                "archive-root/a/b/SKILL.md": SKILL_MD,
                "archive-root/top/SKILL.md": SKILL_MD,
            }
        )
        result = ZipInstaller()._extract_skill(payload, None)
        assert set(result.files) == {"SKILL.md"}

    @pytest.mark.asyncio
    async def test_missing_skill_md_raises(self) -> None:
        payload = _zip_bytes({"readme.md": b"x"})
        with pytest.raises(ValueError, match=r"SKILL\.md not found in ZIP"):
            ZipInstaller()._extract_skill(payload, None)

    @pytest.mark.asyncio
    async def test_subdirectory_without_manifest_raises(self) -> None:
        payload = _zip_bytes({"other/x.txt": b"x"})
        with pytest.raises(ValueError, match=r"SKILL\.md or plugin\.json not found"):
            ZipInstaller()._extract_skill(payload, "absent")

    @pytest.mark.asyncio
    async def test_plugin_only_archive_uses_default_name(self) -> None:
        payload = _zip_bytes({"plugin.json": b"{not json", "other.txt": b"x"})
        result = ZipInstaller()._extract_skill(payload, None)
        assert result.name == "agent-plugin"
        assert result.description == ""

    @pytest.mark.asyncio
    async def test_download_failure_raises(self) -> None:

        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(),
        ) as fetch:
            from types import SimpleNamespace

            fetch.return_value = SimpleNamespace(status_code=404, content=b"")
            with pytest.raises(ValueError, match="HTTP 404"):
                await ZipInstaller()._download_zip("https://example.invalid/a.zip")

    @pytest.mark.asyncio
    async def test_oversized_download_raises(self) -> None:
        from myrm_agent_harness.core.security.http.secure_fetch import ContentTooLargeError

        with (
            patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
                new=AsyncMock(side_effect=ContentTooLargeError("too big")),
            ),
            pytest.raises(ValueError, match="ZIP too large"),
        ):
            await ZipInstaller()._download_zip("https://example.invalid/a.zip")

    @pytest.mark.asyncio
    async def test_download_returns_content(self) -> None:
        from types import SimpleNamespace

        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=SimpleNamespace(status_code=200, content=b"PK")),
        ):
            assert await ZipInstaller()._download_zip("https://example.invalid/a.zip") == b"PK"

    @pytest.mark.asyncio
    async def test_download_forwards_limits(self) -> None:
        from types import SimpleNamespace

        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=SimpleNamespace(status_code=200, content=b"PK")),
        ) as fetch:
            await ZipInstaller()._download_zip("https://example.invalid/a.zip")
        assert fetch.await_args.kwargs["max_content_length"] == MAX_ZIP_SIZE
        assert fetch.await_args.kwargs["timeout"] == ZIP_DOWNLOAD_TIMEOUT


def _batch_zip(files: dict[str, bytes]) -> bytes:
    return _zip_bytes(files)


class TestHermesBatchParser:
    def test_parses_directory_grouped_skills(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            HermesBatchParser,
        )

        payload = _batch_zip(
            {
                "alpha/SKILL.md": SKILL_MD,
                "alpha/notes.md": b"extra",
                "beta/SKILL.md": b"---\nname: Beta\ndescription: b\n---\n# Beta\n",
            }
        )
        skills = HermesBatchParser().parse_zip(payload)
        by_name = {s.name: s for s in skills}
        assert set(by_name) == {"Alpha", "Beta"}
        assert by_name["Alpha"].files["notes.md"] == b"extra"

    def test_parses_root_level_skill(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            HermesBatchParser,
        )

        payload = _batch_zip({"SKILL.md": SKILL_MD})
        skills = HermesBatchParser().parse_zip(payload)
        assert [s.name for s in skills] == ["Alpha"]

    def test_root_level_skill_without_name_falls_back(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            HermesBatchParser,
        )

        payload = _batch_zip({"SKILL.md": b"no frontmatter body"})
        assert [s.name for s in HermesBatchParser().parse_zip(payload)] == ["unnamed_skill"]

    def test_alternate_markdown_is_promoted(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            HermesBatchParser,
        )

        payload = _batch_zip({"alpha/README.md": SKILL_MD})
        skills = HermesBatchParser().parse_zip(payload)
        assert skills[0].name == "Alpha"
        assert "SKILL.md" in skills[0].files

    def test_group_without_markdown_is_skipped(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            HermesBatchParser,
        )

        payload = _batch_zip({"alpha/data.bin": b"\x00\x01"})
        assert HermesBatchParser().parse_zip(payload) == []

    def test_trigger_keywords_are_appended(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            HermesBatchParser,
        )

        payload = _batch_zip({"alpha/SKILL.md": b"---\nname: A\ndescription: d\ntrigger_keywords: [x, y]\n---\nbody\n"})
        skill = HermesBatchParser().parse_zip(payload)[0]
        assert "x, y" in skill.description
        assert skill.metadata["trigger_keywords"] == ["x", "y"]

    def test_single_string_keyword_is_wrapped(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            HermesBatchParser,
        )

        payload = _batch_zip({"alpha/SKILL.md": b"---\nname: A\ntrigger_keywords: solo\n---\nbody\n"})
        assert "solo" in HermesBatchParser().parse_zip(payload)[0].description

    def test_malformed_frontmatter_is_tolerated(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            HermesBatchParser,
        )

        payload = _batch_zip({"alpha/SKILL.md": b"---\nbroken: [\n---\nbody\n"})
        assert [s.name for s in HermesBatchParser().parse_zip(payload)] == ["alpha"]

    def test_skill_md_content_decodes(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            HermesImportedSkill,
        )

        skill = HermesImportedSkill(name="A", description="d", content="c")
        skill.files["SKILL.md"] = b"# body"
        assert skill.skill_md_content == "# body"

    def test_skill_md_content_defaults_empty(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            HermesImportedSkill,
        )

        assert HermesImportedSkill(name="A", description="d", content="c").skill_md_content == ""

    def test_excluded_paths_are_filtered(self) -> None:
        from myrm_agent_harness.agent.skills.market.installers.batch_installer import (
            _is_excluded_file as batch_excluded,
        )

        assert batch_excluded("a/node_modules/b.txt") is True
        assert batch_excluded("a/.DS_Store") is True
        assert batch_excluded("a/__MACOSX/b") is True
        assert batch_excluded("alpha/SKILL.md") is False

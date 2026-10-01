"""Unit tests for the remaining branches of the skill market service.

[INPUT]
- myrm_agent_harness.agent.skills.market.service

[OUTPUT]
- pytest suite covering install-error classification, search cache eviction,
  plugin preview parsing, prerequisites merging, URL installs, cascade
  uninstall, atomic replace rollback, and plugin sub-skill unpacking.

[POS]
myrm-agent-harness/tests/agent/skills/market/test_service_branches.py
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.plugins.manifest import PLUGIN_SCHEMA
from myrm_agent_harness.agent.skills.market.service import (
    BaseSkillMarketService,
    _atomic_replace,
    _resolve_install_error,
)
from myrm_agent_harness.backends.skills.local_skill_id import local_skill_id_from_path
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


@pytest.fixture
def service() -> BaseSkillMarketService:
    return BaseSkillMarketService()


def _async_return(value: object) -> AsyncMock:
    return AsyncMock(return_value=value)


def _downloaded(name: str, files: dict[str, bytes]) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(name=name, description="from archive", files=files, version="1.0.0")


def _skill_md(name: str = "pdf", version: str = "1.0.0") -> bytes:
    return f"---\nname: {name}\ndescription: d\nversion: {version}\n---\n# body\n".encode()


def _detail(**kwargs: object) -> SkillSearchResult:
    payload: dict[str, object] = {
        "id": "acme/skills/pdf",
        "name": "pdf",
        "description": "d",
        "source": "github",
        "author": "acme",
        "install_url": "https://github.com/acme/skills.git",
        "install_method": "git",
    }
    payload.update(kwargs)
    return SkillSearchResult(**payload)  # type: ignore[arg-type]


class TestResolveInstallError:
    def test_unclassified_error_returns_empty_code(self) -> None:
        assert _resolve_install_error(ValueError("plain failure")) == ("plain failure", "")

    def test_category_bucket_collision(self) -> None:
        from myrm_agent_harness.backends.skills.scanning.path_security import (
            CategoryBucketCollisionError,
        )

        assert _resolve_install_error(CategoryBucketCollisionError("clash")) == ("clash", "CATEGORY_BUCKET_COLLISION")

    def test_path_redirect_attack(self) -> None:
        from myrm_agent_harness.backends.skills.scanning.path_security import (
            PathRedirectSecurityError,
        )

        assert _resolve_install_error(PathRedirectSecurityError("redirect"))[1] == "PATH_REDIRECT_ATTACK"


class TestAtomicReplace:
    def test_creates_destination(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("a")

        _atomic_replace(src, tmp_path / "dst")

        assert (tmp_path / "dst" / "a.txt").read_text() == "a"
        assert not src.exists()

    def test_replaces_existing_and_drops_backup(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "new.txt").write_text("new")
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "old.txt").write_text("old")

        _atomic_replace(src, dst)

        assert (dst / "new.txt").read_text() == "new"
        assert not (dst / "old.txt").exists()
        assert not (tmp_path / "dst.bak").exists()

    def test_removes_stale_bak_files(self, tmp_path: Path) -> None:
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "stale.bak").write_text("stale")
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("a")

        _atomic_replace(src, dst)

        assert not (dst / "stale.bak").exists()

    def test_rolls_back_when_move_fails(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "keep.txt").write_text("keep")

        with (
            patch("myrm_agent_harness.agent.skills.market.service.shutil.move", side_effect=OSError("boom")),
            pytest.raises(OSError, match="boom"),
        ):
            _atomic_replace(src, dst)

        assert (dst / "keep.txt").read_text() == "keep"


class TestSearchCache:
    @pytest.mark.asyncio
    async def test_evicts_oldest_entry_at_capacity(self, service: BaseSkillMarketService) -> None:
        from myrm_agent_harness.agent.skills.market.service import CACHE_MAX_ENTRIES

        class _Empty:
            source_name = "custom"

            async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
                return []

        service._sources = [_Empty()]
        service._search_cache.clear()

        for i in range(CACHE_MAX_ENTRIES):
            await service.search(f"q{i}", limit=5)
        assert len(service._search_cache) == CACHE_MAX_ENTRIES

        await service.search("overflow", limit=5)
        assert len(service._search_cache) == CACHE_MAX_ENTRIES

    @pytest.mark.asyncio
    async def test_timed_out_source_is_skipped(self, service: BaseSkillMarketService) -> None:
        import asyncio

        import myrm_agent_harness.agent.skills.market.service as service_mod

        class _Slow:
            source_name = "custom"

            async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
                await asyncio.sleep(30)

        service._sources = [_Slow()]
        with patch.object(service_mod, "SEARCH_TIMEOUT", 0.05):
            assert await service.search("q", limit=5) == []

    @pytest.mark.asyncio
    async def test_source_error_is_skipped(self, service: BaseSkillMarketService) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        class _Broken:
            source_name = "custom"

            async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
                raise RuntimeError("offline")

        service._sources = [_Broken()]
        with patch.object(service, "_search_source", side_effect=RuntimeError("boom")):
            assert await service.search("q", limit=5) == []
        assert service_mod is not None

    @pytest.mark.asyncio
    async def test_blank_query_browses_without_hitting_sources(self, service: BaseSkillMarketService) -> None:
        class _Counting:
            source_name = "custom"
            calls = 0

            async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
                self.calls += 1
                return []

        source = _Counting()
        service._sources = [source]
        service._search_cache.clear()

        assert await service.search("   ", limit=5) == []
        assert source.calls == 0


class TestPreviewExtras:
    @pytest.mark.asyncio
    async def test_preview_detects_agent_plugin(self, service: BaseSkillMarketService) -> None:
        files = {
            "plugin.json": json.dumps({"name": "pdfsuite", "version": "1.0.0", "$schema": PLUGIN_SCHEMA}).encode(),
            "SKILL.md": _skill_md("pdfsuite"),
            "skills/extract/SKILL.md": _skill_md("extract"),
        }
        with (
            patch.object(BaseSkillMarketService, "get_detail", return_value=_detail()),
            patch.object(type(service._git_installer), "download", new=_async_return(_downloaded("pdf", files))),
            patch("myrm_agent_harness.agent.skills.market.service.scan_all_text_files") as scan,
        ):
            from types import SimpleNamespace

            scan.return_value = SimpleNamespace(findings=[], is_clean=True)
            preview = await service.preview("acme/skills/pdf", "github")

        assert preview.package_type == "agent_plugin"
        assert preview.installed_skills == ["extract"]

    @pytest.mark.asyncio
    async def test_preview_merges_prerequisites_from_manifest_and_file(self, service: BaseSkillMarketService) -> None:
        files = {
            "SKILL.md": _skill_md(),
            "requirements.json": json.dumps({"binaries": ["git"]}).encode(),
        }
        detail = _detail(extra_manifest={"requirements": {"env": ["TOKEN"]}})
        report = type("R", (), {"to_dict": lambda self: {"missing_env": ["TOKEN"], "missing_binaries": ["git"]}})()
        with (
            patch.object(BaseSkillMarketService, "get_detail", return_value=detail),
            patch.object(type(service._git_installer), "download", new=_async_return(_downloaded("pdf", files))),
            patch("myrm_agent_harness.agent.skills.market.service.scan_all_text_files") as scan,
            patch(
                "myrm_agent_harness.backends.skills.prerequisites.check_skill_prerequisites",
                return_value=report,
            ) as check,
        ):
            from types import SimpleNamespace

            scan.return_value = SimpleNamespace(findings=[], is_clean=True)
            preview = await service.preview("acme/skills/pdf", "github")

        assert preview.prerequisites == {"missing_env": ["TOKEN"], "missing_binaries": ["git"]}
        assert check.call_args.args[1] == {"env": ["TOKEN"], "binaries": ["git"]}

    @pytest.mark.asyncio
    async def test_preview_survives_malformed_requirements_json(self, service: BaseSkillMarketService) -> None:
        files = {"SKILL.md": _skill_md(), "requirements.json": b"{not json"}
        with (
            patch.object(BaseSkillMarketService, "get_detail", return_value=_detail()),
            patch.object(type(service._git_installer), "download", new=_async_return(_downloaded("pdf", files))),
            patch("myrm_agent_harness.agent.skills.market.service.scan_all_text_files") as scan,
        ):
            from types import SimpleNamespace

            scan.return_value = SimpleNamespace(findings=[], is_clean=True)
            preview = await service.preview("acme/skills/pdf", "github")

        assert preview.prerequisites is None

    @pytest.mark.asyncio
    async def test_preview_rejects_unsupported_install_method(self, service: BaseSkillMarketService) -> None:
        with (
            patch.object(
                BaseSkillMarketService,
                "get_detail",
                return_value=_detail(install_method="svn"),
            ),
            pytest.raises(ValueError, match="Unsupported install method"),
        ):
            await service.preview("acme/skills/pdf", "github")


class TestInstallFromUrl:
    @pytest.mark.asyncio
    async def test_rejects_unparseable_url(self, service: BaseSkillMarketService) -> None:
        result = await service.install_from_url("")
        assert result.success is False
        assert result.error

    @pytest.mark.asyncio
    async def test_reports_download_failure(self, service: BaseSkillMarketService) -> None:
        with patch.object(
            type(service._git_installer),
            "download",
            new=AsyncMock(side_effect=ValueError("clone refused")),
        ):
            result = await service.install_from_url("https://github.com/acme/skills")

        assert result.success is False
        assert "clone refused" in (result.error or "")

    @pytest.mark.asyncio
    async def test_emits_resolving_stage(self, service: BaseSkillMarketService) -> None:
        stages: list[tuple[str, str]] = []
        with patch.object(
            type(service._git_installer),
            "download",
            new=AsyncMock(side_effect=ValueError("clone refused")),
        ):
            await service.install_from_url(
                "https://github.com/acme/skills",
                progress_callback=lambda _sid, stage, msg: stages.append((stage, msg)),  # type: ignore[arg-type]
            )

        assert ("resolving", "Parsing URL...") in stages
        assert ("downloading", "Cloning repository...") in stages


class TestCascadeUninstall:
    @pytest.mark.asyncio
    async def test_removes_children_of_parent_plugin(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        target = install_dir / "pdf"
        target.mkdir()
        (target / "SKILL.md").write_text("x")
        (install_dir / "child").mkdir()
        (install_dir / "unrelated").mkdir()

        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)
        monkeypatch.setattr(service_mod, "write_receipt_file", lambda *a, **k: None)
        monkeypatch.setattr(
            service_mod,
            "read_origin",
            lambda path: {"parent_plugin": "pdf"} if path.name == "child" else {},
        )
        skill_id = local_skill_id_from_path(target)

        with patch.object(service_mod, "read_receipt_file", return_value=None):
            result = await service.uninstall(skill_id)

        assert result.success is True
        assert not (install_dir / "child").exists()
        assert (install_dir / "unrelated").exists()
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_reports_removal_failure(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        target = install_dir / "pdf"
        target.mkdir()
        (target / "SKILL.md").write_text("x")

        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)
        monkeypatch.setattr(service_mod, "write_receipt_file", lambda *a, **k: None)
        monkeypatch.setattr(service_mod, "read_origin", lambda path: {})
        skill_id = local_skill_id_from_path(target)

        with (
            patch.object(service_mod, "read_receipt_file", return_value=None),
            patch.object(service_mod.shutil, "rmtree", side_effect=OSError("locked")),
        ):
            result = await service.uninstall(skill_id)

        assert result.success is False
        assert "Failed to remove skill directory" in (result.error or "")

    @pytest.mark.asyncio
    async def test_rejects_unknown_local_id(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)

        result = await service.uninstall("local::" + "0" * 16)
        assert result.success is False
        assert "not found" in (result.error or "")


class TestQuarantineInstallBranches:
    @pytest.mark.asyncio
    async def test_unpacks_plugin_sub_skills(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)
        monkeypatch.setattr(service_mod, "write_receipt_file", lambda *a, **k: None)

        files = {
            "plugin.json": json.dumps({"name": "pdfsuite", "version": "1.0.0", "$schema": PLUGIN_SCHEMA}).encode(),
            "SKILL.md": _skill_md("pdfsuite"),
            "skills/extract/SKILL.md": _skill_md("extract"),
        }
        result = await service._quarantine_install("acme/skills/pdfsuite", "pdfsuite", files, source="github")

        assert result.success is True
        assert (install_dir / "pdfsuite" / "plugin.json").exists()
        assert (install_dir / "extract" / "SKILL.md").exists()
        assert "extract" in result.installed_skills

    @pytest.mark.asyncio
    async def test_survives_broken_plugin_manifest(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)
        monkeypatch.setattr(service_mod, "write_receipt_file", lambda *a, **k: None)

        files = {"plugin.json": b"{not json", "SKILL.md": _skill_md("broken")}
        result = await service._quarantine_install("acme/skills/broken", "broken", files, source="github")

        assert result.success is True
        assert (install_dir / "broken" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_reuses_existing_install_and_reads_current_version(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        existing = install_dir / "pdf"
        existing.mkdir()
        (existing / "SKILL.md").write_bytes(_skill_md("pdf", "0.9.0"))
        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)
        monkeypatch.setattr(service_mod, "write_receipt_file", lambda *a, **k: None)

        result = await service._quarantine_install(
            "acme/skills/pdf", "pdf", {"SKILL.md": _skill_md("pdf", "1.0.0")}, source="github"
        )

        assert result.success is True
        assert b"1.0.0" in (install_dir / "pdf" / "SKILL.md").read_bytes()

    @pytest.mark.asyncio
    async def test_blocks_downgrade_without_allow_flag(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        existing = install_dir / "pdf"
        existing.mkdir()
        (existing / "SKILL.md").write_bytes(_skill_md("pdf", "2.0.0"))
        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)
        monkeypatch.setattr(service_mod, "write_receipt_file", lambda *a, **k: None)

        result = await service._quarantine_install(
            "acme/skills/pdf", "pdf", {"SKILL.md": _skill_md("pdf", "1.0.0")}, source="github"
        )

        assert result.success is False
        assert b"2.0.0" in (existing / "SKILL.md").read_bytes()

    @pytest.mark.asyncio
    async def test_skips_path_escape_entries(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)
        monkeypatch.setattr(service_mod, "write_receipt_file", lambda *a, **k: None)

        result = await service._quarantine_install(
            "acme/skills/pdf",
            "pdf",
            {"SKILL.md": _skill_md(), "../escape.md": b"nope"},
            source="github",
        )

        assert result.success is True
        assert not (install_dir / "escape.md").exists()

    @pytest.mark.asyncio
    async def test_reports_scan_findings(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)
        monkeypatch.setattr(service_mod, "write_receipt_file", lambda *a, **k: None)

        from myrm_agent_harness.backends.skills.scanning.scanner import (
            ScanFinding,
            ScanResult,
            ScanSeverity,
        )

        dirty = ScanResult(
            skill_name="pdf",
            findings=[
                ScanFinding(
                    threat_type="test_note",
                    severity=ScanSeverity.LOW,
                    description="suspicious note",
                    line_number=1,
                )
            ],
        )
        with patch(
            "myrm_agent_harness.agent.skills.market.service.scan_all_text_files",
            return_value=dirty,
        ):
            result = await service._quarantine_install(
                "acme/skills/pdf", "pdf", {"SKILL.md": _skill_md()}, source="github"
            )

        assert result.success is True
        assert result.scan_summary


class TestUnsafeInstallTarget:
    @pytest.mark.asyncio
    async def test_symlinked_target_is_rejected_cleanly(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """安装目标是符号链接时返回结构化失败，而不是抛出 500。"""
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        real = install_dir / "real"
        real.mkdir()
        (real / "keep.txt").write_text("original")
        (install_dir / "pdf").symlink_to(real, target_is_directory=True)
        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)
        monkeypatch.setattr(service_mod, "write_receipt_file", lambda *a, **k: None)

        result = await service._quarantine_install("acme/skills/pdf", "pdf", {"SKILL.md": _skill_md()}, source="github")

        assert result.success is False
        assert result.error_code == "PATH_REDIRECT_ATTACK"
        assert (real / "keep.txt").read_text() == "original"

    @pytest.mark.asyncio
    async def test_rejection_emits_progress_stage(
        self,
        service: BaseSkillMarketService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import myrm_agent_harness.agent.skills.market.service as service_mod

        install_dir = tmp_path / "skills"
        install_dir.mkdir()
        real = install_dir / "real"
        real.mkdir()
        (install_dir / "pdf").symlink_to(real, target_is_directory=True)
        monkeypatch.setattr(service_mod, "LOCAL_INSTALL_DIR", install_dir)
        monkeypatch.setattr(service_mod, "write_receipt_file", lambda *a, **k: None)
        stages: list[tuple[str, str]] = []

        await service._quarantine_install(
            "acme/skills/pdf",
            "pdf",
            {"SKILL.md": _skill_md()},
            source="github",
            progress_callback=lambda _sid, stage, _msg: stages.append((stage, _msg)),  # type: ignore[arg-type]
        )

        assert any(stage == "rejected" for stage, _ in stages)


class TestUnsafeSkillNames:
    @pytest.mark.parametrize(
        "name",
        ["", ".", "..", "a/b", "a\\b", "/abs/path", "../escape", "sub/../../x"],
    )
    @pytest.mark.asyncio
    async def test_rejects_unsafe_names_cleanly(self, service: BaseSkillMarketService, name: str) -> None:
        result = await service._quarantine_install("evil/id", name, {"SKILL.md": _skill_md()}, source="github")
        assert result.success is False
        assert result.error_code == "INVALID_SKILL_NAME"

    @pytest.mark.parametrize("name", ["pdf", "my skill", "技能-1.0", "a.b_c"])
    def test_accepts_legitimate_names(self, name: str) -> None:
        from myrm_agent_harness.agent.skills.market.service import _is_safe_skill_dir_name

        assert _is_safe_skill_dir_name(name) is True

    @pytest.mark.asyncio
    async def test_rejection_emits_progress_stage(self, service: BaseSkillMarketService) -> None:
        stages: list[str] = []
        await service._quarantine_install(
            "evil/id",
            "../escape",
            {"SKILL.md": _skill_md()},
            source="github",
            progress_callback=lambda _sid, stage, _msg: stages.append(stage),  # type: ignore[arg-type]
        )
        assert stages == ["rejected"]

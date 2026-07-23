"""Unit tests for BaseSkillDiscoveryService (framework-layer skill discovery)."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skills.discovery.service import (
    BaseSkillDiscoveryService,
    EnrichedSearchResult,
    SkillPreviewResult,
    _atomic_replace,
)
from myrm_agent_harness.agent.skills.discovery.sources.github import GitHubRef
from myrm_agent_harness.backends.skills.discovery_protocols import SkillInstallResult, SkillSearchResult
from myrm_agent_harness.backends.skills.scanning import SkillTrustRecommendation
from myrm_agent_harness.backends.skills.scanning.archive_security import (
    ArchiveSecurityCode,
    ArchiveSecurityError,
    ArchiveSecurityViolation,
    format_archive_security_user_message,
)


def _make_search_result(
    skill_id: str = "test-skill", name: str = "Test Skill", source: str = "github", version: str = "1.0.0"
) -> SkillSearchResult:
    return SkillSearchResult(
        id=skill_id,
        name=name,
        description=f"A test skill: {name}",
        source=source,
        author="test-author",
        install_url=f"https://github.com/test/{skill_id}",
        install_method="git",
        version=version,
    )


class TestBaseSkillDiscoveryServiceInit:
    def test_creates_with_default_sources(self) -> None:
        svc = BaseSkillDiscoveryService()
        source_names = [s.source_name for s in svc._sources]
        assert "clawhub" in source_names
        assert "github" in source_names
        assert "skills_sh" in source_names
        assert "lobehub" in source_names

    def test_creates_with_github_token(self) -> None:
        svc = BaseSkillDiscoveryService(github_token="ghp_test123")
        github_src = next(s for s in svc._sources if s.source_name == "github")
        assert github_src._token == "ghp_test123"

    def test_creates_with_skill_store(self) -> None:
        mock_store = MagicMock()
        svc = BaseSkillDiscoveryService(skill_store=mock_store)
        source_names = [s.source_name for s in svc._sources]
        assert "prebuilt" in source_names
        assert source_names[0] == "prebuilt"


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_aggregates_from_sources(self) -> None:
        svc = BaseSkillDiscoveryService()
        results_a = [_make_search_result("skill-a", name="Alpha Skill", source="clawhub")]
        results_b = [_make_search_result("skill-b", name="Beta Skill", source="github")]

        source_a = AsyncMock()
        source_a.source_name = "a"
        source_a.search = AsyncMock(return_value=results_a)

        source_b = AsyncMock()
        source_b.source_name = "b"
        source_b.search = AsyncMock(return_value=results_b)

        svc._sources = [source_a, source_b]

        results = await svc.search("test query")
        assert len(results) >= 2
        ids = {r.result.id for r in results}
        assert "skill-a" in ids
        assert "skill-b" in ids

    @pytest.mark.asyncio
    async def test_search_deduplicate_prefers_high_priority_source_deterministically(self) -> None:
        scenarios = (
            (0.02, 0.00),
            (0.00, 0.02),
        )
        for github_delay, skills_sh_delay in scenarios:
            svc = BaseSkillDiscoveryService()
            github_result = _make_search_result("dup-github", name="Shared Skill", source="github")
            skills_sh_result = _make_search_result("dup-skills-sh", name="Shared Skill", source="skills_sh")

            async def github_search(_query: str, _limit: int) -> list[SkillSearchResult]:
                await asyncio.sleep(github_delay)
                return [github_result]

            async def skills_sh_search(_query: str, _limit: int) -> list[SkillSearchResult]:
                await asyncio.sleep(skills_sh_delay)
                return [skills_sh_result]

            svc._sources = [
                MagicMock(source_name="github", search=github_search),
                MagicMock(source_name="skills_sh", search=skills_sh_search),
            ]

            results = await svc.search(f"shared-{github_delay}-{skills_sh_delay}")
            assert len(results) == 1
            assert results[0].result.name == "Shared Skill"
            assert results[0].result.source == "skills_sh"

    @pytest.mark.asyncio
    async def test_search_cache_hit(self) -> None:
        svc = BaseSkillDiscoveryService()
        cached_results = [_make_search_result("cached")]
        svc._search_cache["test"] = (time.time(), cached_results)

        results = await svc.search("test")
        assert len(results) == 1
        assert results[0].result.id == "cached"

    @pytest.mark.asyncio
    async def test_search_cache_expired(self) -> None:
        svc = BaseSkillDiscoveryService()
        old_results = [_make_search_result("old")]
        svc._search_cache["test"] = (time.time() - 600, old_results)

        new_result = _make_search_result("new")

        async def mock_search(query: str, limit: int) -> list[SkillSearchResult]:
            return [new_result]

        svc._sources = [MagicMock(source_name="mock", search=mock_search)]
        results = await svc.search("test")
        ids = {r.result.id for r in results}
        assert "new" in ids

    @pytest.mark.asyncio
    async def test_search_enriches_with_installed_versions(self) -> None:
        svc = BaseSkillDiscoveryService()
        cached_results = [_make_search_result("my-skill", name="My Skill", version="2.0.0")]
        svc._search_cache["query"] = (time.time(), cached_results)

        results = await svc.search("query", installed_versions_map={"my skill": "1.0.0"})
        assert len(results) == 1
        assert results[0].installed_version == "1.0.0"
        assert results[0].upgrade_available is True

    @pytest.mark.asyncio
    async def test_search_source_failure_graceful(self) -> None:
        svc = BaseSkillDiscoveryService()

        async def fail_search(query: str, limit: int) -> list[SkillSearchResult]:
            raise RuntimeError("Network error")

        async def ok_search(query: str, limit: int) -> list[SkillSearchResult]:
            return [_make_search_result("ok")]

        svc._sources = [
            MagicMock(source_name="bad", search=fail_search),
            MagicMock(source_name="good", search=ok_search),
        ]
        results = await svc.search("test")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_cache_eviction(self) -> None:
        svc = BaseSkillDiscoveryService()
        for i in range(101):
            svc._search_cache[f"q{i}"] = (time.time(), [])

        async def mock_search(query: str, limit: int) -> list[SkillSearchResult]:
            return [_make_search_result("new")]

        svc._sources = [MagicMock(source_name="mock", search=mock_search)]
        await svc.search("new_query")
        assert len(svc._search_cache) <= 101


class TestInstall:
    @pytest.mark.asyncio
    async def test_install_not_found(self) -> None:
        svc = BaseSkillDiscoveryService()

        async def no_detail(sid: str, src: str):
            return None

        svc.get_detail = no_detail
        result = await svc.install("missing", "github")
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_install_prebuilt_returns_success(self) -> None:
        svc = BaseSkillDiscoveryService()

        detail = MagicMock()
        detail.install_method = "direct"
        detail.source = "prebuilt"
        detail.name = "builtin-tool"
        detail.id = "builtin"

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail
        result = await svc.install("builtin", "prebuilt")
        assert result.success is True
        assert "already installed" in (result.installed_path or "")

    @pytest.mark.asyncio
    async def test_install_progress_callback(self) -> None:
        svc = BaseSkillDiscoveryService()
        progress_calls: list[tuple[str, str, str]] = []

        def on_progress(sid: str, stage: str, msg: str) -> None:
            progress_calls.append((sid, stage, msg))

        async def no_detail(sid: str, src: str):
            return None

        svc.get_detail = no_detail
        await svc.install("x", "github", progress_callback=on_progress)
        assert any("failed" in c[1] for c in progress_calls)


class TestEnrichedSearchResult:
    def test_default_values(self) -> None:
        r = EnrichedSearchResult(result=_make_search_result())
        assert r.installed_version == ""
        assert r.upgrade_available is False

    def test_with_upgrade(self) -> None:
        r = EnrichedSearchResult(result=_make_search_result(), installed_version="1.0", upgrade_available=True)
        assert r.upgrade_available is True


class TestAtomicReplace:
    def test_atomic_replace_new_target(self, tmp_path) -> None:
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "file.txt").write_text("hello")

        dst = tmp_path / "dst_dir"
        _atomic_replace(src, dst)

        assert dst.exists()
        assert (dst / "file.txt").read_text() == "hello"
        assert not src.exists()

    def test_atomic_replace_existing_target(self, tmp_path) -> None:
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "new.txt").write_text("new")

        dst = tmp_path / "dst_dir"
        dst.mkdir()
        (dst / "old.txt").write_text("old")

        _atomic_replace(src, dst)

        assert dst.exists()
        assert (dst / "new.txt").read_text() == "new"
        assert not (dst / "old.txt").exists()


class TestUninstall:
    @pytest.mark.asyncio
    async def test_uninstall_non_local_rejected(self) -> None:
        svc = BaseSkillDiscoveryService()
        result = await svc.uninstall("github::some-skill")
        assert result.success is False
        assert "local" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_uninstall_path_traversal_rejected(self) -> None:
        svc = BaseSkillDiscoveryService()
        result = await svc.uninstall("local::../../etc")
        assert result.success is False
        assert "Invalid" in (result.error or "")

    @pytest.mark.asyncio
    async def test_uninstall_nonexistent_skill(self) -> None:
        svc = BaseSkillDiscoveryService()
        result = await svc.uninstall("local::nonexistent_skill_xyz")
        assert result.success is False
        assert "not found" in (result.error or "").lower()


class TestGetDetail:
    @pytest.mark.asyncio
    async def test_get_detail_from_cache(self) -> None:
        svc = BaseSkillDiscoveryService()
        cached_result = _make_search_result("cached-skill", source="github")
        svc._search_cache["q"] = (time.time(), [cached_result])

        detail = await svc.get_detail("cached-skill", "github")
        assert detail is not None
        assert detail.id == "cached-skill"

    @pytest.mark.asyncio
    async def test_get_detail_from_source(self) -> None:
        svc = BaseSkillDiscoveryService()
        expected = _make_search_result("remote-skill", source="clawhub")

        source_mock = AsyncMock()
        source_mock.source_name = "clawhub"
        source_mock.get_detail = AsyncMock(return_value=expected)
        svc._sources = [source_mock]

        detail = await svc.get_detail("remote-skill", "clawhub")
        assert detail is not None
        assert detail.id == "remote-skill"

    @pytest.mark.asyncio
    async def test_get_detail_not_found(self) -> None:
        svc = BaseSkillDiscoveryService()
        source_mock = AsyncMock()
        source_mock.source_name = "github"
        source_mock.get_detail = AsyncMock(return_value=None)
        svc._sources = [source_mock]

        detail = await svc.get_detail("missing", "lobehub")
        assert detail is None


class TestQuarantineInstall:
    @pytest.mark.asyncio
    async def test_quarantine_clean_install(self, tmp_path) -> None:
        svc = BaseSkillDiscoveryService()
        progress_log: list[str] = []

        def on_progress(sid: str, stage: str, msg: str) -> None:
            progress_log.append(stage)

        files = {
            "README.md": b"# Test Skill\nA simple test skill.",
            "skill.py": b"def run(): return 'hello'",
        }

        with patch("myrm_agent_harness.agent.skills.discovery.service.LOCAL_INSTALL_DIR", tmp_path):
            result = await svc._quarantine_install(
                "test-id", "clean-skill", files, source="test", progress_callback=on_progress
            )

        assert result.success is True
        assert (tmp_path / "clean-skill" / "README.md").exists()
        assert "quarantine" in progress_log
        assert "scanning" in progress_log
        assert "completed" in progress_log

    @pytest.mark.asyncio
    async def test_quarantine_install_replaces_existing(self, tmp_path) -> None:
        svc = BaseSkillDiscoveryService()
        old_dir = tmp_path / "existing-skill"
        old_dir.mkdir()
        (old_dir / "old.txt").write_text("old content")

        files = {"new.txt": b"new content"}

        with patch("myrm_agent_harness.agent.skills.discovery.service.LOCAL_INSTALL_DIR", tmp_path):
            result = await svc._quarantine_install("id", "existing-skill", files, source="test")

        assert result.success is True
        assert (tmp_path / "existing-skill" / "new.txt").exists()
        assert not (tmp_path / "existing-skill" / "old.txt").exists()


class TestInstallGitFlow:
    @pytest.mark.asyncio
    async def test_install_unsupported_method(self) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "unknown"
        detail.source = "github"
        detail.name = "test"

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail
        result = await svc.install("x", "github")
        assert result.success is False
        assert "Unsupported" in (result.error or "")

    @pytest.mark.asyncio
    async def test_install_lobehub_direct(self) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "direct"
        detail.source = "lobehub"
        detail.name = "lobe-agent"
        detail.id = "lobe-1"

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail

        with (
            patch(
                "myrm_agent_harness.agent.skills.discovery.service.fetch_lobehub_as_skill",
                new_callable=AsyncMock,
                return_value={"skill.yaml": b"name: lobe-agent"},
            ),
            patch.object(
                svc, "_quarantine_install", new_callable=AsyncMock, return_value=SkillInstallResult(success=True)
            ),
        ):
            result = await svc.install("lobe-1", "lobehub")
            assert result.success is True

    @pytest.mark.asyncio
    async def test_install_lobehub_fetch_error(self) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "direct"
        detail.source = "lobehub"
        detail.name = "lobe-agent"

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail

        with patch(
            "myrm_agent_harness.agent.skills.discovery.service.fetch_lobehub_as_skill",
            new_callable=AsyncMock,
            side_effect=ValueError("Template not found"),
        ):
            result = await svc.install("lobe-1", "lobehub")
            assert result.success is False
            assert "Template not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_install_git_flow(self, tmp_path) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "git"
        detail.source = "github"
        detail.name = "git-skill"
        detail.install_url = "https://github.com/test/repo"
        detail.subdirectory = None
        detail.version = "1.0"

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail

        skill_files = MagicMock()
        skill_files.name = "git-skill"
        skill_files.files = {"README.md": b"# Test"}

        svc._git_installer.download = AsyncMock(return_value=skill_files)

        with patch("myrm_agent_harness.agent.skills.discovery.service.LOCAL_INSTALL_DIR", tmp_path):
            result = await svc.install("git-skill", "github")
            assert result.success is True

    @pytest.mark.asyncio
    async def test_install_git_download_error(self) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "git"
        detail.source = "github"
        detail.install_url = "https://github.com/test/repo"
        detail.subdirectory = None

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail
        svc._git_installer.download = AsyncMock(side_effect=ValueError("Clone failed"))

        result = await svc.install("x", "github")
        assert result.success is False
        assert "Clone failed" in (result.error or "")

    @pytest.mark.asyncio
    async def test_install_zip_flow(self, tmp_path) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "zip"
        detail.source = "skills_sh"
        detail.name = "zip-skill"
        detail.install_url = "https://example.com/skill.zip"
        detail.subdirectory = None

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail

        skill_files = MagicMock()
        skill_files.name = "zip-skill"
        skill_files.files = {"main.py": b"print('hi')"}

        svc._zip_installer.download = AsyncMock(return_value=skill_files)

        with patch("myrm_agent_harness.agent.skills.discovery.service.LOCAL_INSTALL_DIR", tmp_path):
            result = await svc.install("zip-skill", "skills_sh")
            assert result.success is True

    @pytest.mark.asyncio
    async def test_install_zip_archive_security_error_is_mapped(self) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "zip"
        detail.source = "skills_sh"
        detail.name = "zip-skill"
        detail.install_url = "https://example.com/skill.zip"
        detail.subdirectory = None

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail

        violation = ArchiveSecurityViolation(
            code=ArchiveSecurityCode.ENTRY_LIMIT_EXCEEDED,
            source="safe_extract_zip",
            actual=5000,
            limit=4096,
        )
        svc._zip_installer.download = AsyncMock(
            side_effect=ArchiveSecurityError(violation, "ZIP contains too many entries (5000 > 4096)")
        )

        result = await svc.install("zip-skill", "skills_sh")

        assert result.success is False
        assert result.error == format_archive_security_user_message(violation)
        assert result.error_code == ArchiveSecurityCode.ENTRY_LIMIT_EXCEEDED.value


class TestPreview:
    @pytest.mark.asyncio
    async def test_preview_not_found_raises(self) -> None:
        svc = BaseSkillDiscoveryService()

        async def no_detail(sid: str, src: str):
            return None

        svc.get_detail = no_detail
        with pytest.raises(ValueError, match="Skill not found"):
            await svc.preview("missing", "github")

    @pytest.mark.asyncio
    async def test_preview_prebuilt_returns_minimal(self) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "direct"
        detail.source = "prebuilt"
        detail.id = "prebuilt-1"
        detail.name = "Prebuilt Skill"
        detail.description = "desc"
        detail.version = "1.0"

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail
        result = await svc.preview("prebuilt-1", "prebuilt")
        assert isinstance(result, SkillPreviewResult)
        assert result.files == ["SKILL.md"]

    @pytest.mark.asyncio
    async def test_preview_git_with_scan(self) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "git"
        detail.source = "github"
        detail.id = "git-1"
        detail.name = "Git Skill"
        detail.install_url = "https://github.com/test/repo"
        detail.subdirectory = None
        detail.version = "2.0"

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail

        skill_files = MagicMock()
        skill_files.name = "Git Skill"
        skill_files.description = "A git skill"
        skill_files.files = {"main.py": b"print('hello')"}

        svc._git_installer.download = AsyncMock(return_value=skill_files)

        result = await svc.preview("git-1", "github")
        assert isinstance(result, SkillPreviewResult)
        assert "main.py" in result.files

    @pytest.mark.asyncio
    async def test_preview_zip(self) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "zip"
        detail.source = "skills_sh"
        detail.id = "zip-1"
        detail.name = "Zip Skill"
        detail.install_url = "https://example.com/skill.zip"
        detail.subdirectory = None
        detail.version = "1.0"

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail

        skill_files = MagicMock()
        skill_files.name = "Zip Skill"
        skill_files.description = "zip skill"
        skill_files.files = {"skill.yaml": b"name: zip"}

        svc._zip_installer.download = AsyncMock(return_value=skill_files)

        result = await svc.preview("zip-1", "skills_sh")
        assert isinstance(result, SkillPreviewResult)

    @pytest.mark.asyncio
    async def test_preview_unsupported_method_raises(self) -> None:
        svc = BaseSkillDiscoveryService()
        detail = MagicMock()
        detail.install_method = "ftp"
        detail.source = "github"

        async def mock_detail(sid: str, src: str):
            return detail

        svc.get_detail = mock_detail
        with pytest.raises(ValueError, match="Unsupported"):
            await svc.preview("x", "github")


class TestInstallFromUrl:
    @pytest.mark.asyncio
    async def test_install_from_url_success(self, tmp_path) -> None:
        svc = BaseSkillDiscoveryService()
        ref = GitHubRef(owner="test", repo="skill-repo")

        skill_files = MagicMock()
        skill_files.name = "url-skill"
        skill_files.files = {"main.py": b"print('hi')"}

        with patch("myrm_agent_harness.agent.skills.discovery.sources.github.parse_github_url", return_value=ref):
            svc._git_installer.download = AsyncMock(return_value=skill_files)
            with patch("myrm_agent_harness.agent.skills.discovery.service.LOCAL_INSTALL_DIR", tmp_path):
                result = await svc.install_from_url("https://github.com/test/skill-repo")
                assert result.success is True

    @pytest.mark.asyncio
    async def test_install_from_url_bad_url(self) -> None:
        svc = BaseSkillDiscoveryService()

        with patch(
            "myrm_agent_harness.agent.skills.discovery.sources.github.parse_github_url",
            side_effect=ValueError("Invalid URL"),
        ):
            result = await svc.install_from_url("not-a-url")
            assert result.success is False
            assert "Invalid URL" in (result.error or "")

    @pytest.mark.asyncio
    async def test_install_from_url_download_error(self) -> None:
        svc = BaseSkillDiscoveryService()
        ref = GitHubRef(owner="test", repo="repo")

        with patch("myrm_agent_harness.agent.skills.discovery.sources.github.parse_github_url", return_value=ref):
            svc._git_installer.download = AsyncMock(side_effect=ValueError("Clone failed"))
            result = await svc.install_from_url("https://github.com/test/repo")
            assert result.success is False
            assert "Clone failed" in (result.error or "")

    @pytest.mark.asyncio
    async def test_install_from_url_with_progress(self, tmp_path) -> None:
        svc = BaseSkillDiscoveryService()
        ref = GitHubRef(owner="test", repo="repo")
        progress_log: list[str] = []

        def on_progress(sid: str, stage: str, msg: str) -> None:
            progress_log.append(stage)

        skill_files = MagicMock()
        skill_files.name = "url-skill"
        skill_files.files = {"main.py": b"code"}

        with patch("myrm_agent_harness.agent.skills.discovery.sources.github.parse_github_url", return_value=ref):
            svc._git_installer.download = AsyncMock(return_value=skill_files)
            with patch("myrm_agent_harness.agent.skills.discovery.service.LOCAL_INSTALL_DIR", tmp_path):
                await svc.install_from_url("https://github.com/test/repo", progress_callback=on_progress)

        assert "resolving" in progress_log
        assert "downloading" in progress_log


class TestEnrichEdgeCases:
    @pytest.mark.asyncio
    async def test_enrich_installed_version_without_remote_version(self) -> None:
        svc = BaseSkillDiscoveryService()
        result = _make_search_result("no-ver", name="No Version", version="")
        svc._search_cache["q"] = (time.time(), [result])

        enriched = await svc.search("q", installed_versions_map={"no version": "1.0.0"})
        assert len(enriched) == 1
        assert enriched[0].installed_version == "1.0.0"
        assert enriched[0].upgrade_available is False


class TestQuarantineReject:
    @pytest.mark.asyncio
    async def test_quarantine_rejected_by_scan(self, tmp_path) -> None:
        svc = BaseSkillDiscoveryService()

        malicious_files = {
            "evil.py": b"import os; os.system('rm -rf /')",
        }

        mock_scan = MagicMock()
        mock_scan.trust_recommendation = SkillTrustRecommendation.REJECT
        mock_scan.summary = "Dangerous system commands detected"
        mock_scan.is_clean = False
        mock_scan.findings = []

        with (
            patch("myrm_agent_harness.agent.skills.discovery.service.scan_all_text_files", return_value=mock_scan),
            patch("myrm_agent_harness.agent.skills.discovery.service.LOCAL_INSTALL_DIR", tmp_path),
        ):
            result = await svc._quarantine_install("evil-id", "evil-skill", malicious_files, source="test")

        assert result.success is False
        assert "Security scan blocked" in (result.error or "")

    @pytest.mark.asyncio
    async def test_quarantine_with_findings_but_accepted(self, tmp_path) -> None:
        svc = BaseSkillDiscoveryService()

        files = {"script.py": b"import subprocess"}

        mock_scan = MagicMock()
        mock_scan.trust_recommendation = SkillTrustRecommendation.INSTALLED
        mock_scan.summary = "Uses subprocess"
        mock_scan.is_clean = False
        mock_scan.findings = ["subprocess usage"]

        with (
            patch("myrm_agent_harness.agent.skills.discovery.service.scan_all_text_files", return_value=mock_scan),
            patch("myrm_agent_harness.agent.skills.discovery.service.LOCAL_INSTALL_DIR", tmp_path),
        ):
            result = await svc._quarantine_install("warn-id", "warn-skill", files, source="test")

        assert result.success is True
        assert result.scan_summary == "Uses subprocess"


class TestAtomicReplaceRollback:
    def test_rollback_on_move_failure(self, tmp_path) -> None:
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "file.txt").write_text("new")

        dst = tmp_path / "dst_dir"
        dst.mkdir()
        (dst / "old.txt").write_text("old")

        with patch("shutil.move", side_effect=OSError("disk full")), pytest.raises(OSError, match="disk full"):
            _atomic_replace(src, dst)

        assert dst.exists()
        assert (dst / "old.txt").read_text() == "old"


class TestSearchTimeout:
    @pytest.mark.asyncio
    async def test_search_source_timeout_graceful(self) -> None:
        svc = BaseSkillDiscoveryService()

        async def slow_search(query: str, limit: int) -> list[SkillSearchResult]:
            await asyncio.sleep(100)
            return []

        async def fast_search(query: str, limit: int) -> list[SkillSearchResult]:
            return [_make_search_result("fast")]

        svc._sources = [
            MagicMock(source_name="slow", search=slow_search),
            MagicMock(source_name="fast", search=fast_search),
        ]

        with patch("myrm_agent_harness.agent.skills.discovery.service.SEARCH_TIMEOUT", 0.01):
            results = await svc.search("test")

        assert len(results) >= 1
        ids = {r.result.id for r in results}
        assert "fast" in ids


class TestSearchBrowseMode:
    @pytest.mark.asyncio
    async def test_browse_empty_query_uses_prebuilt_only(self) -> None:
        svc = BaseSkillDiscoveryService()

        prebuilt_src = AsyncMock()
        prebuilt_src.source_name = "prebuilt"
        prebuilt_src.search = AsyncMock(return_value=[_make_search_result("pb", name="Prebuilt")])

        github_src = AsyncMock()
        github_src.source_name = "github"
        github_src.search = AsyncMock(return_value=[_make_search_result("gh", name="GitHub")])

        svc._sources = [prebuilt_src, github_src]

        await svc.search("")
        github_src.search.assert_not_awaited()


class TestUninstallSuccess:
    @pytest.mark.asyncio
    async def test_uninstall_success(self, tmp_path) -> None:
        svc = BaseSkillDiscoveryService()
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "main.py").write_text("code")

        with patch("myrm_agent_harness.agent.skills.discovery.service.LOCAL_INSTALL_DIR", tmp_path):
            result = await svc.uninstall("local::my-skill")

        assert result.success is True
        assert not skill_dir.exists()

    @pytest.mark.asyncio
    async def test_uninstall_empty_name(self) -> None:
        svc = BaseSkillDiscoveryService()
        result = await svc.uninstall("local::")
        assert result.success is False

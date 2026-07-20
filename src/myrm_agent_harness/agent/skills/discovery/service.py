"""Skill discovery service.

Aggregates search results from multiple sources, orchestrates install flow.
Implements SkillDiscoveryBackend protocol.

[INPUT]
- backends.skills.discovery_protocols::SkillInstallResult, (POS: SkillBackend SkillBackend SkillDiscoveryBackend)
- backends.skills.scanning::ScanFinding, (POS: Scan result cache layer. Stores scan results in Volume (~/.myrm/skill_scans/) to avoid redundant scanning. Critical for performance: 20x speedup for repeat scans. Cache key: SHA256 hash of skill content Cache location: ~/.myrm/skill_scans/{content_hash}.json Expiration: 60 days TTL (auto-cleanup on get))
- backends.skills.scanning.archive_security::format_archive_security_user_message (POS: Canonical archive-security contract for typed/untyped ZIP guard errors.)

[OUTPUT]
- EnrichedSearchResult: Search result enriched with local installation info.
- SkillPreviewResult: Preview result before installation (includes security scan).
- BaseSkillDiscoveryService: Aggregates skill sources for search deduplication and qua...

[POS]
Skill discovery service.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.backends.skills.discovery_protocols import SkillInstallResult, SkillSearchResult
from myrm_agent_harness.backends.skills.scanning.archive_security import (
    classify_archive_security_issue,
    format_archive_security_user_message,
)

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.discovery_protocols import InstalledSkillStore
from myrm_agent_harness.agent.skills.discovery.sanitizer import sanitize_skill_files
from myrm_agent_harness.backends.skills.scanning import ScanFinding, SkillTrustRecommendation
from myrm_agent_harness.backends.skills.versioning import compare_versions

from .helpers import deduplicate, fetch_lobehub_as_skill, rank_results, scan_all_text_files, write_origin
from .installers.git_installer import GitInstaller
from .installers.zip_installer import ZipInstaller
from .sources.aliyun import AliyunSource
from .sources.base import SkillSource
from .sources.clawhub import ClawHubSource
from .sources.github import GitHubSkillSource
from .sources.lobehub import LobeHubSource
from .sources.modelscope import ModelScopeSource
from .sources.prebuilt import PrebuiltSkillSource
from .sources.skills_sh import SkillsShSource

logger = logging.getLogger(__name__)

LOCAL_INSTALL_DIR = Path("~/.myrm/skills").expanduser()
SEARCH_TIMEOUT = 20.0
CACHE_MAX_ENTRIES = 100
CACHE_TTL_SECONDS = 300


def _resolve_install_error(error: ValueError) -> tuple[str, str]:
    violation = classify_archive_security_issue(error)
    if violation is None:
        return str(error), ""
    return format_archive_security_user_message(violation), violation.code.value


@dataclass(frozen=True)
class EnrichedSearchResult:
    """Search result enriched with local installation info."""

    result: SkillSearchResult
    installed_version: str = ""
    upgrade_available: bool = False


@dataclass(frozen=True)
class SkillPreviewResult:
    """Preview result before installation (includes security scan)."""

    skill_id: str
    name: str
    description: str
    version: str
    files: list[str]
    scan_findings: list[ScanFinding] = field(default_factory=list)
    is_clean: bool = True


class BaseSkillDiscoveryService:
    """Aggregates skill sources for search deduplication and quarantine-based install.
    Framework-layer service: does not depend on server database or event bus.
    """

    def __init__(self, github_token: str | None = None, skill_store: InstalledSkillStore | None = None) -> None:
        sources: list[SkillSource] = [
            ClawHubSource(),
            GitHubSkillSource(token=github_token),
            SkillsShSource(),
            LobeHubSource(),
            ModelScopeSource(),
            AliyunSource(),
        ]
        if skill_store:
            sources.insert(0, PrebuiltSkillSource(skill_store))
        self._sources: list[SkillSource] = sources
        self._git_installer = GitInstaller()
        self._zip_installer = ZipInstaller()
        self._search_cache: dict[str, tuple[float, list[SkillSearchResult]]] = {}

    async def search(
        self, query: str, limit: int = 30, installed_versions_map: dict[str, str] | None = None
    ) -> list[EnrichedSearchResult]:
        import time

        cache_key = query.lower().strip()
        is_browse = not cache_key
        now = time.time()

        cached = self._search_cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            raw_results = cached[1][:limit]
        else:
            if is_browse:
                sources = [s for s in self._sources if s.source_name == "prebuilt"]
            else:
                sources = self._sources

            tasks = [self._search_source(source, query, limit) for source in sources]

            all_results: list[SkillSearchResult] = []
            for coro in asyncio.as_completed(tasks):
                try:
                    results = await asyncio.wait_for(coro, timeout=SEARCH_TIMEOUT)
                    all_results.extend(results)
                except TimeoutError:
                    logger.warning("A skill source timed out during search")
                except Exception as e:
                    logger.warning("Skill source search error: %s", e)

            deduped = deduplicate(all_results)
            ranked = rank_results(deduped, query)
            raw_results = ranked[:limit]

            if len(self._search_cache) >= CACHE_MAX_ENTRIES:
                oldest_key = min(self._search_cache, key=lambda k: self._search_cache[k][0])
                del self._search_cache[oldest_key]
            self._search_cache[cache_key] = (now, raw_results)

        return self._enrich_results(raw_results, installed_versions_map)

    async def preview(self, skill_id: str, source: str) -> SkillPreviewResult:
        """Download skill content and run security scan without installing."""
        detail = await self.get_detail(skill_id, source)
        if not detail:
            raise ValueError(f"Skill not found: {skill_id} from {source}")

        if detail.install_method == "direct" and detail.source == "prebuilt":
            return SkillPreviewResult(
                skill_id=detail.id,
                name=detail.name,
                description=detail.description,
                version=detail.version,
                files=["SKILL.md"],
            )

        if detail.install_method == "git":
            skill_files = await self._git_installer.download(detail.install_url, detail.subdirectory)
        elif detail.install_method == "zip":
            skill_files = await self._zip_installer.download(detail.install_url, detail.subdirectory)
        else:
            raise ValueError(f"Unsupported install method: {detail.install_method}")

        scan_result = scan_all_text_files(detail.name, skill_files.files)

        return SkillPreviewResult(
            skill_id=detail.id,
            name=skill_files.name,
            description=skill_files.description,
            version=detail.version,
            files=sorted(skill_files.files.keys()),
            scan_findings=list(scan_result.findings),
            is_clean=scan_result.is_clean,
        )

    async def install(
        self, skill_id: str, source: str, progress_callback: Callable[[str, str, str], None] | None = None
    ) -> SkillInstallResult:
        def _emit(stage: str, msg: str):
            if progress_callback:
                progress_callback(skill_id, stage, msg)

        _emit("resolving", "Resolving skill metadata...")
        detail = await self.get_detail(skill_id, source)
        if not detail:
            _emit("failed", "Skill not found")
            return SkillInstallResult(success=False, error=f"Skill not found: {skill_id} from {source}")

        if detail.install_method == "direct" and detail.source == "prebuilt":
            _emit("completed", "Prebuilt skill ready")
            return SkillInstallResult(
                success=True, skill_name=detail.name, skill_id=detail.id, installed_path="prebuilt (already installed)"
            )

        if detail.install_method == "direct" and detail.source == "lobehub":
            _emit("downloading", "Fetching LobeHub agent template...")
            try:
                files = await fetch_lobehub_as_skill(detail)
            except ValueError as e:
                resolved_error, error_code = _resolve_install_error(e)
                _emit("failed", resolved_error)
                return SkillInstallResult(success=False, error=resolved_error, error_code=error_code)
            return await self._quarantine_install(
                skill_id, detail.name, files, source=source, progress_callback=progress_callback
            )

        _emit("downloading", f"Downloading from {source}...")
        try:
            if detail.install_method == "git":
                skill_files = await self._git_installer.download(detail.install_url, detail.subdirectory)
            elif detail.install_method == "zip":
                skill_files = await self._zip_installer.download(detail.install_url, detail.subdirectory)
            else:
                _emit("failed", "Unsupported install method")
                return SkillInstallResult(success=False, error=f"Unsupported install method: {detail.install_method}")
        except ValueError as e:
            resolved_error, error_code = _resolve_install_error(e)
            _emit("failed", resolved_error)
            return SkillInstallResult(success=False, error=resolved_error, error_code=error_code)

        sanitized = sanitize_skill_files(skill_files.files)
        return await self._quarantine_install(
            skill_id, skill_files.name, sanitized, source=source, progress_callback=progress_callback
        )

    async def install_from_url(
        self, url: str, progress_callback: Callable[[str, str, str], None] | None = None
    ) -> SkillInstallResult:
        from .sources.github import parse_github_url

        skill_id = f"url::{url[:80]}"

        def _emit(stage: str, msg: str):
            if progress_callback:
                progress_callback(skill_id, stage, msg)

        _emit("resolving", "Parsing URL...")

        try:
            ref = parse_github_url(url)
        except ValueError as e:
            _emit("failed", str(e))
            return SkillInstallResult(success=False, error=str(e))

        _emit("downloading", "Cloning repository...")
        try:
            skill_files = await self._git_installer.download(ref.clone_url, subdirectory=ref.subdirectory, ref=ref.ref)
        except ValueError as e:
            resolved_error, error_code = _resolve_install_error(e)
            _emit("failed", resolved_error)
            return SkillInstallResult(success=False, error=resolved_error, error_code=error_code)

        sanitized = sanitize_skill_files(skill_files.files)
        return await self._quarantine_install(
            skill_id, skill_files.name, sanitized, source="github", progress_callback=progress_callback
        )

    async def uninstall(self, skill_id: str) -> SkillInstallResult:
        """Uninstall a locally installed skill."""
        if not skill_id.startswith("local::"):
            return SkillInstallResult(
                success=False, error=f"Only local skills can be uninstalled via this method: {skill_id}"
            )

        skill_name = skill_id.removeprefix("local::")
        if not skill_name or "/" in skill_name or "\\" in skill_name or ".." in skill_name:
            return SkillInstallResult(success=False, error=f"Invalid skill name: {skill_name}")

        target_dir = LOCAL_INSTALL_DIR / skill_name

        if not target_dir.exists():
            return SkillInstallResult(success=False, error=f"Skill directory not found: {target_dir}")

        try:
            shutil.rmtree(target_dir)
        except Exception as e:
            return SkillInstallResult(success=False, error=f"Failed to remove skill directory: {e}")

        logger.info("Uninstalled skill: %s", skill_name)
        return SkillInstallResult(
            success=True, skill_name=skill_name, skill_id=skill_id, installed_path=str(target_dir)
        )

    async def get_detail(self, skill_id: str, source: str) -> SkillSearchResult | None:
        cached = self._find_in_cache(skill_id, source)
        if cached:
            return cached

        for src in self._sources:
            if src.source_name == source:
                return await src.get_detail(skill_id)
        return None

    def _find_in_cache(self, skill_id: str, source: str) -> SkillSearchResult | None:
        for _ts, results in self._search_cache.values():
            for r in results:
                if r.id == skill_id and r.source == source:
                    return r
        return None

    def _enrich_results(
        self, results: list[SkillSearchResult], installed_versions: dict[str, str] | None
    ) -> list[EnrichedSearchResult]:
        if not installed_versions or not results:
            return [EnrichedSearchResult(result=r) for r in results]

        enriched: list[EnrichedSearchResult] = []
        for r in results:
            local_ver = installed_versions.get(r.name.lower(), "")
            if local_ver and r.version:
                delta = compare_versions(local_ver, r.version)
                enriched.append(
                    EnrichedSearchResult(result=r, installed_version=local_ver, upgrade_available=delta.has_update)
                )
            elif local_ver:
                enriched.append(EnrichedSearchResult(result=r, installed_version=local_ver))
            else:
                enriched.append(EnrichedSearchResult(result=r))
        return enriched

    async def _search_source(self, source: SkillSource, query: str, limit: int) -> list[SkillSearchResult]:
        try:
            return await source.search(query, limit)
        except Exception as e:
            logger.warning("Search failed for source %s: %s", source.source_name, e)
            return []

    async def _quarantine_install(
        self,
        skill_id: str,
        name: str,
        files: dict[str, bytes],
        *,
        source: str = "",
        progress_callback: Callable[[str, str, str], None] | None = None,
    ) -> SkillInstallResult:
        def _emit(stage: str, msg: str):
            if progress_callback:
                progress_callback(skill_id, stage, msg)

        quarantine_dir = Path(tempfile.mkdtemp(prefix=f"skill-quarantine-{name}-"))

        try:
            _emit("quarantine", "Writing to quarantine...")
            quarantine_resolved = quarantine_dir.resolve()
            for rel_path, content in files.items():
                file_path = (quarantine_dir / rel_path).resolve()
                if not str(file_path).startswith(str(quarantine_resolved)):
                    logger.warning("Blocked path escape in skill '%s': %s", name, rel_path)
                    continue
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(content)

            _emit("scanning", "Running security scan...")
            scan_result = scan_all_text_files(name, files)

            if scan_result.trust_recommendation == SkillTrustRecommendation.REJECT:
                logger.warning("Skill '%s' rejected by security scan: %s", name, scan_result.summary)
                _emit("rejected", scan_result.summary)
                return SkillInstallResult(
                    success=False,
                    skill_name=name,
                    error=f"Security scan blocked installation: {scan_result.summary}",
                    scan_summary=scan_result.summary,
                )

            _emit("installing", "Promoting to install directory...")
            target_dir = LOCAL_INSTALL_DIR / name
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            _atomic_replace(quarantine_dir, target_dir)

            write_origin(target_dir, source=source, skill_id=skill_id)

            scan_summary = scan_result.summary if not scan_result.is_clean else ""
            if scan_summary:
                logger.warning("Installed skill with findings: %s -> %s (%s)", name, target_dir, scan_summary)
            else:
                logger.info("Installed skill: %s -> %s", name, target_dir)

            _emit("completed", f"Installed to {target_dir}")
            return SkillInstallResult(
                success=True,
                skill_name=name,
                skill_id=f"local::{name}",
                installed_path=str(target_dir),
                scan_summary=scan_summary,
            )
        finally:
            if quarantine_dir.exists():
                shutil.rmtree(quarantine_dir, ignore_errors=True)


def _atomic_replace(src: Path, dst: Path) -> None:
    backup = dst.parent / (dst.name + ".bak")
    had_backup = False

    try:
        if dst.exists():
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            dst.rename(backup)
            had_backup = True

        shutil.move(str(src), str(dst))

        if had_backup:
            shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        if had_backup and backup.exists() and not dst.exists():
            backup.rename(dst)
        raise

"""Domain skill store — executable-layer domain-level learning.

Manages manifest-based domain skill declarations. Each manifest maps a set
of domain patterns to Python tool scripts that can be executed in the browser
session sandbox (reuses ``execute_script`` AST safety).

Complements ``SiteExperienceStore`` (prompt-layer knowledge) with an
executable layer: SiteExperience tells the Agent *what to avoid*;
DomainSkillStore tells the Agent *which ready-made tools to call*.

[INPUT]
- (none)

[OUTPUT]
- DomainSkillStore: Domain skill registry with manifest loading and domain matching.
- get_global_domain_skill_store: Singleton accessor.

[POS]
Executable-layer domain skill store.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from .types import DomainSkillManifest, DomainTool

logger = logging.getLogger(__name__)

_global_store: DomainSkillStore | None = None


def get_global_domain_skill_store() -> DomainSkillStore:
    """Get global domain skill store (singleton)."""
    global _global_store
    if _global_store is None:
        _global_store = DomainSkillStore()
    return _global_store


def _domain_matches(hostname: str, pattern: str) -> bool:
    """Check if hostname matches a domain pattern (supports ``*.`` wildcard prefix)."""
    normalized = pattern.lower().strip().rstrip(".")
    if normalized.startswith("*."):
        suffix = normalized[2:]
        return hostname.endswith(f".{suffix}")
    return hostname == normalized


def _normalize_hostname(hostname: str) -> str:
    """Normalize hostname: lowercase, strip trailing dot and www. prefix."""
    h = hostname.lower().strip().rstrip(".")
    if h.startswith("www."):
        h = h[4:]
    return h


class DomainSkillStore:
    """Registry for domain executable skills.

    Loads manifests from:
    1. Builtin directory (bundled with harness)
    2. User directory (``MYRM_DATA_DIR/domain_skills/``)

    Thread-safe via ``threading.RLock``.
    """

    def __init__(
        self,
        *,
        user_dir: str | Path | None = None,
        load_builtin: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._manifests: dict[str, DomainSkillManifest] = {}
        self._manifest_dirs: dict[str, Path] = {}

        if load_builtin:
            self._load_directory(self._builtin_dir())
        user_path = self._resolve_user_dir(user_dir)
        if user_path.exists():
            self._load_directory(user_path)

        logger.info(
            "DomainSkillStore initialized: %d manifests loaded",
            len(self._manifests),
        )

    @staticmethod
    def _builtin_dir() -> Path:
        return Path(__file__).parent / "builtin"

    @staticmethod
    def _resolve_user_dir(path: str | Path | None) -> Path:
        if path is not None:
            return Path(path)
        data_dir = os.environ.get("MYRM_DATA_DIR", "")
        if data_dir:
            return Path(data_dir) / "domain_skills"
        if os.path.exists("/workspace/"):
            return Path("/workspace/.myrm/domain_skills")
        return Path.home() / ".myrm" / "domain_skills"

    def _load_directory(self, directory: Path) -> None:
        """Load all manifest.json files under *directory* (one level deep)."""
        if not directory.is_dir():
            return
        for child in sorted(directory.iterdir()):
            if not child.is_dir() or child.name.startswith("_"):
                continue
            manifest_path = child / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = self._parse_manifest(manifest_path)
                with self._lock:
                    self._manifests[manifest.id] = manifest
                    self._manifest_dirs[manifest.id] = child
            except Exception:
                logger.warning(
                    "Failed to load domain skill manifest: %s",
                    manifest_path,
                    exc_info=True,
                )

    @staticmethod
    def _parse_manifest(path: Path) -> DomainSkillManifest:
        """Parse a manifest.json into a ``DomainSkillManifest``."""
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        skill_id: str = raw.get("id", path.parent.name)
        name: str = raw.get("name", skill_id)
        domains = tuple(raw.get("domains", []))

        python_tools: dict[str, DomainTool] = {}
        for tool_name, tool_raw in raw.get("python_tools", {}).items():
            python_tools[tool_name] = DomainTool(
                name=tool_name,
                description=tool_raw.get("description", ""),
                script_path=tool_raw.get("path", ""),
                callable_name=tool_raw.get("callable", tool_name),
                args=tool_raw.get("args", {}),
                returns_description=tool_raw.get("returns", ""),
            )

        return DomainSkillManifest(
            id=skill_id,
            name=name,
            domains=domains,
            python_tools=python_tools,
        )

    def match(self, url: str) -> list[DomainSkillManifest]:
        """Return all manifests whose domain patterns match *url*."""
        hostname = self._extract_hostname(url)
        if not hostname:
            return []

        with self._lock:
            return [
                m
                for m in self._manifests.values()
                if any(_domain_matches(hostname, d) for d in m.domains)
            ]

    def get(self, skill_id: str) -> DomainSkillManifest | None:
        """Return manifest by ID."""
        with self._lock:
            return self._manifests.get(skill_id)

    def get_tool_script_path(self, skill_id: str, tool_name: str) -> Path | None:
        """Resolve absolute path to the Python script for a domain tool."""
        with self._lock:
            manifest = self._manifests.get(skill_id)
            base_dir = self._manifest_dirs.get(skill_id)
        if manifest is None or base_dir is None:
            return None
        tool = manifest.python_tools.get(tool_name)
        if tool is None:
            return None
        return base_dir / tool.script_path

    def list_skills(self) -> list[DomainSkillManifest]:
        """Return all loaded manifests."""
        with self._lock:
            return list(self._manifests.values())

    def add_user_skill(
        self,
        manifest: DomainSkillManifest,
        skill_dir: Path,
    ) -> None:
        """Register a user-created domain skill (for semi-automatic distillation)."""
        with self._lock:
            self._manifests[manifest.id] = manifest
            self._manifest_dirs[manifest.id] = skill_dir

    def is_builtin(self, skill_id: str) -> bool:
        """Check if a skill is a builtin (shipped with harness)."""
        with self._lock:
            skill_dir = self._manifest_dirs.get(skill_id)
        if skill_dir is None:
            return False
        try:
            return skill_dir.resolve().is_relative_to(self._builtin_dir().resolve())
        except (ValueError, OSError):
            return False

    def delete_skill(self, skill_id: str) -> bool:
        """Remove a domain skill from registry (does not delete files)."""
        with self._lock:
            removed = self._manifests.pop(skill_id, None) is not None
            self._manifest_dirs.pop(skill_id, None)
            return removed

    @staticmethod
    def _extract_hostname(url: str) -> str:
        try:
            from urllib.parse import urlparse

            parsed = (
                urlparse(url)
                if "://" in str(url)
                else urlparse(f"https://{url}")
            )
            return _normalize_hostname(parsed.hostname or "")
        except Exception:
            return ""

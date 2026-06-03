"""Automatic detection of CLI agent backends.

Discovers installed CLI tools (claude, codex, gemini) by searching PATH,
common installation paths, and npm global. Caches results to avoid
repeated filesystem scans.

[INPUT]
- (none)

[OUTPUT]
- DetectedBackend: A detected CLI backend with its path and version.
- BackendDetector: Detects available CLI agent backends.

[POS]
Automatic detection of CLI agent backends.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from myrm_agent_harness.toolkits.acp.auth.credential_store import CredentialState

logger = logging.getLogger(__name__)

from myrm_agent_harness.toolkits.acp.toolchains import TOOLCHAIN_BASE_DIR

_KNOWN_BACKENDS = ("claude", "codex", "gemini")

_COMMON_PATHS = (
    TOOLCHAIN_BASE_DIR / "bin",  # Check isolated toolchain first
    Path.home() / ".local" / "bin",
    Path("/usr/local/bin"),
    Path("/opt/homebrew/bin"),
)


@dataclass(frozen=True, slots=True)
class DetectedBackend:
    """A detected CLI backend with its path and version."""

    name: str
    path: str
    version: str | None = None


@dataclass
class BackendDetector:
    """Detects available CLI agent backends.

    Searches for known CLI tools using ``shutil.which``, common paths,
    and npm global. Optionally runs ``--version`` to detect the version.

    Results are cached after the first detection.
    """

    _cache: list[DetectedBackend] | None = field(default=None, init=False, repr=False)

    async def detect(self, *, include_version: bool = True) -> list[DetectedBackend]:
        """Detect all available backends.

        Args:
            include_version: If True, run ``<cmd> --version`` to get version info.

        Returns:
            List of detected backends (cached after first call).
        """
        if self._cache is not None:
            return self._cache

        results: list[DetectedBackend] = []
        for name in _KNOWN_BACKENDS:
            path = self._find_executable(name)
            if path is None:
                continue

            version = None
            if include_version:
                version = await self._get_version(path)

            results.append(DetectedBackend(name=name, path=path, version=version))
            logger.info("backend_detected name=%s path=%s version=%s", name, path, version)

        self._cache = results
        return results

    async def detect_with_auth(
        self,
        *,
        env: Mapping[str, str] | None = None,
        include_version: bool = True,
    ) -> list[tuple[DetectedBackend, CredentialState]]:
        """Detect installed backends and pair each with its current auth state.

        Installation detection is cached (it is effectively static for a process),
        but auth state is resolved fresh on every call because the user can sign in
        or out at any time. Powers the settings page's "installed + logged-in" view.
        """
        from myrm_agent_harness.toolkits.acp.auth import CredentialStore

        store = CredentialStore(env)
        detected = await self.detect(include_version=include_version)
        return [(backend, store.state(backend.name)) for backend in detected]

    def invalidate_cache(self) -> None:
        """Force re-detection on next call."""
        self._cache = None

    def _find_executable(self, name: str) -> str | None:
        """Find an executable by name using multiple strategies."""
        found = shutil.which(name)
        if found:
            return found

        for base_path in _COMMON_PATHS:
            candidate = base_path / name
            if candidate.is_file() and _is_executable(candidate):
                return str(candidate)

        npm_global = self._find_npm_global(name)
        if npm_global:
            return npm_global

        return None

    def _find_npm_global(self, name: str) -> str | None:
        """Check npm global bin directory."""
        npm_prefix = shutil.which("npm")
        if npm_prefix is None:
            return None
        npm_bin = Path(npm_prefix).parent
        candidate = npm_bin / name
        if candidate.is_file() and _is_executable(candidate):
            return str(candidate)
        return None

    async def _get_version(self, path: str) -> str | None:
        """Run ``<path> --version`` and extract version string."""
        try:
            proc = await asyncio.create_subprocess_exec(
                path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            output = stdout.decode("utf-8", errors="replace").strip()
            if output:
                return output.split("\n")[0].strip()
        except (TimeoutError, OSError, FileNotFoundError):
            logger.debug("version_check_failed path=%s", path, exc_info=True)
        return None


def _is_executable(path: Path) -> bool:
    """Check if a path is executable."""
    try:
        return os.access(path, os.X_OK)
    except OSError:
        return False

"""Directory trust store with hierarchical descent matching for workspace security.

[INPUT]
- Directory path strings.

[OUTPUT]
- Canonical directory path strings and boolean trust decisions.

[POS]
- Harness core security module managing trusted filesystem boundaries for remote memory.
"""

from __future__ import annotations

from pathlib import Path


class DirectoryTrustStore:
    """Manages trusted directory roots with hierarchical inheritance support."""

    def __init__(self, initial_trusted_dirs: list[str] | None = None) -> None:
        self._trusted_dirs: set[Path] = set()
        if initial_trusted_dirs:
            for d in initial_trusted_dirs:
                self.trust_directory(d)

    def _canonicalize(self, directory: str | Path) -> Path:
        """Resolve symbolic links and absolute filesystem path."""
        p = Path(directory) if isinstance(directory, str) else directory
        return p.resolve()

    def trust_directory(self, directory: str | Path) -> str:
        """Add a directory to trusted roots. Returns canonical path string."""
        canonical = self._canonicalize(directory)
        self._trusted_dirs.add(canonical)
        return str(canonical)

    def untrust_directory(self, directory: str | Path) -> bool:
        """Remove a directory from trusted roots. Returns True if removed."""
        canonical = self._canonicalize(directory)
        if canonical in self._trusted_dirs:
            self._trusted_dirs.remove(canonical)
            return True
        return False

    def is_directory_trusted(self, directory: str | Path) -> bool:
        """Check whether directory or any ancestor is registered as trusted."""
        target = self._canonicalize(directory)
        return any(
            target == trusted_root or trusted_root in target.parents
            for trusted_root in self._trusted_dirs
        )

    def list_trusted_directories(self) -> list[str]:
        """Return sorted list of all canonical trusted directory paths."""
        return sorted([str(p) for p in self._trusted_dirs])

    def clear(self) -> None:
        """Clear all trusted directory entries."""
        self._trusted_dirs.clear()

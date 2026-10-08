"""Directory trust store for managing explicitly authorized project directories.

[INPUT]
- Local filesystem path (~/.myrm/trusted_directories.json) or custom Path.

[OUTPUT]
- DirectoryTrustStore: Thread-safe canonical storage and lookup for trusted directories.

[POS]
Persistent registry storing normalized canonical paths to prevent path traversal and symlink aliasing attacks.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time


class DirectoryTrustStore:
    """Thread-safe persistent store for trusted project directories."""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        """Initialize the trust store.

        Args:
            storage_path: Optional custom path to store JSON registry.
                          If None, defaults to ~/.myrm/trusted_directories.json.
        """
        self._lock = threading.Lock()
        if storage_path is not None:
            self._storage_path = Path(storage_path).resolve()
        else:
            base_dir = Path(os.path.expanduser("~/.myrm"))
            self._storage_path = (base_dir / "trusted_directories.json").resolve()

        self._trusted_dirs: dict[str, dict[str, float | str]] = {}
        self._load()

    @staticmethod
    def normalize_directory(directory: str | Path) -> str:
        """Normalize directory path to a canonical absolute path without symlinks."""
        return str(Path(directory).resolve())

    def _load(self) -> None:
        """Load trusted directories from disk."""
        if not self._storage_path.exists():
            return
        try:
            content = self._storage_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                self._trusted_dirs = {
                    self.normalize_directory(k): v
                    for k, v in data.items()
                    if isinstance(v, dict)
                }
        except (OSError, json.JSONDecodeError):
            self._trusted_dirs = {}

    def _save(self) -> None:
        """Persist trusted directories to disk atomically."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._storage_path.with_suffix(".tmp")
            content = json.dumps(self._trusted_dirs, indent=2, ensure_ascii=False)
            temp_path.write_text(content, encoding="utf-8")
            temp_path.replace(self._storage_path)
        except OSError:
            # Fallback if disk is read-only or during unit tests in memory
            pass

    def is_trusted(self, directory: str | Path, allow_ancestor: bool = True) -> bool:
        """Check if a directory is currently trusted.

        Args:
            directory: Directory path to check.
            allow_ancestor: If True, returns True if any parent/ancestor directory is trusted.

        Returns:
            True if explicitly trusted or enclosed by a trusted ancestor, False otherwise.
        """
        canonical = self.normalize_directory(directory)
        canonical_path = Path(canonical)
        with self._lock:
            if canonical in self._trusted_dirs:
                return True
            if allow_ancestor:
                for trusted_str in self._trusted_dirs:
                    trusted_path = Path(trusted_str)
                    try:
                        canonical_path.relative_to(trusted_path)
                        return True
                    except ValueError:
                        continue
            return False

    def trust(self, directory: str | Path, reason: str = "manual_grant") -> str:
        """Explicitly authorize and trust a directory.

        Args:
            directory: Directory path to authorize.
            reason: Context or justification for trust.

        Returns:
            Canonical normalized directory path.
        """
        canonical = self.normalize_directory(directory)
        with self._lock:
            self._trusted_dirs[canonical] = {
                "trusted_at": time.time(),
                "reason": reason,
            }
            self._save()
        return canonical

    def untrust(self, directory: str | Path) -> bool:
        """Revoke trust for a directory.

        Args:
            directory: Directory path to revoke.

        Returns:
            True if previously trusted and now revoked, False if was not trusted.
        """
        canonical = self.normalize_directory(directory)
        with self._lock:
            if canonical in self._trusted_dirs:
                del self._trusted_dirs[canonical]
                self._save()
                return True
            return False

    def list_trusted(self) -> list[str]:
        """List all trusted canonical directory paths."""
        with self._lock:
            return sorted(list(self._trusted_dirs.keys()))

    def clear(self) -> None:
        """Clear all trusted directories (useful for test isolation)."""
        with self._lock:
            self._trusted_dirs.clear()
            self._save()

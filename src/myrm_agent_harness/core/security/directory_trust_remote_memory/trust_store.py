"""Directory trust registry maintaining canonical trusted project roots.

[INPUT]
- File paths and directories to trust, untrust, or query.

[OUTPUT]
- Boolean trust determinations and canonicalized directory sets.

[POS]
- Harness core security module preventing untrusted cloned repositories from exfiltrating memories.
"""

from __future__ import annotations

import os


class DirectoryTrustStore:
    """In-memory store of trusted filesystem directory roots with canonical path resolution."""

    def __init__(self, initial_trusted_dirs: list[str] | None = None) -> None:
        self._trusted_paths: set[str] = set()
        if initial_trusted_dirs:
            for d in initial_trusted_dirs:
                self.trust_directory(d)

    @staticmethod
    def _canonicalize(path: str) -> str:
        """Resolve symlinks and normalize to absolute path."""
        expanded = os.path.expanduser(path)
        return os.path.realpath(os.path.abspath(expanded))

    def trust_directory(self, directory: str) -> str:
        """Mark a directory path as trusted and return its canonical path."""
        canon = self._canonicalize(directory)
        self._trusted_paths.add(canon)
        return canon

    def untrust_directory(self, directory: str) -> bool:
        """Remove a directory path from the trusted set."""
        canon = self._canonicalize(directory)
        if canon in self._trusted_paths:
            self._trusted_paths.remove(canon)
            return True
        return False

    def is_directory_trusted(self, directory: str) -> bool:
        """Check whether a directory or any of its parent ancestors is explicitly trusted."""
        try:
            target_canon = self._canonicalize(directory)
            if target_canon in self._trusted_paths:
                return True

            # Check if target resides within any trusted parent root
            for trusted_root in self._trusted_paths:
                # Ensure boundary match: either identical or has directory separator
                if target_canon == trusted_root or target_canon.startswith(
                    trusted_root + os.sep
                ):
                    return True
            return False
        except Exception:
            # Fail closed on any resolution error
            return False

    def list_trusted_directories(self) -> list[str]:
        """Return sorted list of all canonical trusted directory paths."""
        return sorted(self._trusted_paths)

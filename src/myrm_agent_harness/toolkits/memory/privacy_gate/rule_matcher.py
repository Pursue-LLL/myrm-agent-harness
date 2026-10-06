# [POS]: myrm_agent_harness/toolkits/memory/privacy_gate/rule_matcher.py
# [INPUT]: fnmatch, pathlib.Path, re
# [OUTPUT]: PathAndExclusionMatcher
"""Path and content rule matcher for memory privacy boundaries.

Evaluates source file paths, .myrmignore rules, and exclusion patterns
to prevent private credentials or configuration files from entering memory.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import ClassVar


class PathAndExclusionMatcher:
    """Evaluates whether paths or content are prohibited by exclusion policies."""

    DEFAULT_EXCLUDED_PATH_PATTERNS: ClassVar[list[str]] = [
        "*.env",
        "*.env.*",
        ".env*",
        "*.pem",
        "*.key",
        "*id_rsa*",
        "*id_ecdsa*",
        "*id_ed25519*",
        "*credentials*.json",
        "*secrets*.yaml",
        "*secrets*.yml",
        ".netrc",
        ".pgpass",
        "*/.aws/*",
        "*/.ssh/*",
    ]

    def __init__(
        self,
        allow_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        ignore_file_path: Path | str | None = None,
    ) -> None:
        self._allow_patterns: list[str] = list(allow_patterns or [])
        self._exclude_patterns: list[str] = list(self.DEFAULT_EXCLUDED_PATH_PATTERNS)
        if exclude_patterns:
            self._exclude_patterns.extend(exclude_patterns)

        if ignore_file_path is not None:
            self.load_ignore_file(ignore_file_path)

    def load_ignore_file(self, ignore_file_path: Path | str) -> int:
        """Parse gitignore-style exclusion rules from a .myrmignore file.

        Args:
            ignore_file_path: Path to the ignore file.

        Returns:
            Number of newly added rules.
        """
        path = Path(ignore_file_path)
        if not path.is_file():
            return 0

        added_count = 0
        try:
            content = path.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped not in self._exclude_patterns:
                    self._exclude_patterns.append(stripped)
                    added_count += 1
        except Exception:
            return 0
        return added_count

    def is_path_allowed(self, file_path: str | Path) -> bool:
        """Check if path explicitly matches an allowlist pattern."""
        p_str = str(file_path).replace("\\", "/")
        name = Path(p_str).name
        for pattern in self._allow_patterns:
            if fnmatch.fnmatch(p_str, pattern) or fnmatch.fnmatch(name, pattern):
                return True
        return False

    def is_path_excluded(self, file_path: str | Path) -> bool:
        """Check if path matches any exclusion rule (and not whitelisted)."""
        if self.is_path_allowed(file_path):
            return False

        p_str = str(file_path).replace("\\", "/")
        name = Path(p_str).name
        for pattern in self._exclude_patterns:
            if fnmatch.fnmatch(p_str, pattern) or fnmatch.fnmatch(name, pattern):
                return True
        return False

    def check_path(self, file_path: str | Path) -> tuple[bool, str | None]:
        """Validate whether a file path is safe to ingest into memory.

        Returns:
            (is_safe, violation_reason)
        """
        p_str = str(file_path).replace("\\", "/")
        name = Path(p_str).name

        if self.is_path_allowed(file_path):
            return True, None

        for pattern in self._exclude_patterns:
            if fnmatch.fnmatch(p_str, pattern) or fnmatch.fnmatch(name, pattern):
                return False, f"Path '{p_str}' matches excluded memory pattern '{pattern}'"

        return True, None

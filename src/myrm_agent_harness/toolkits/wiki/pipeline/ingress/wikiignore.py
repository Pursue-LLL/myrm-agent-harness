"""Vault `.wikiignore` pattern loader (gitignore-like, simplified).

[INPUT]
- core.structure.WikiStructure (POS: vault directory layout)

[OUTPUT]
- load_wikiignore_patterns, write_wikiignore_patterns, path_matches_wikiignore

[POS]
User-defined import/dedup exclusion rules at vault root.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

_WIKIIGNORE_FILENAME = ".wikiignore"


def wikiignore_path(structure: WikiStructure) -> Path:
    return structure.base_dir / _WIKIIGNORE_FILENAME


def load_wikiignore_patterns(structure: WikiStructure) -> tuple[str, ...]:
    path = wikiignore_path(structure)
    if not path.is_file():
        return ()
    lines = path.read_text(encoding="utf-8").splitlines()
    patterns: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return tuple(patterns)


def write_wikiignore_patterns(structure: WikiStructure, content: str) -> None:
    structure.base_dir.mkdir(parents=True, exist_ok=True)
    wikiignore_path(structure).write_text(content, encoding="utf-8")


def path_matches_wikiignore(relative_posix: str, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return False
    normalized = relative_posix.replace("\\", "/").lstrip("/")
    name = Path(normalized).name
    for pattern in patterns:
        pat = pattern.replace("\\", "/")
        if "/" in pat:
            if fnmatch.fnmatch(normalized, pat) or fnmatch.fnmatch(normalized, f"**/{pat}"):
                return True
        elif fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(normalized, f"**/{pat}"):
            return True
    return False

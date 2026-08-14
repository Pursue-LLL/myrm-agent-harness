#!/usr/bin/env python3
"""Validate markdown backtick path references across a repo tree.

Backtick spans that carry a directory separator are resolved for existence in
a deterministic order:

1. explicit relatives (``./`` / ``../``) — against the md file's directory,
   plus the table row's first-cell directory when present;
2. cross-repo aliases (``myrm-agent-server/...`` etc.) — against the monorepo
   root, with the ``myrm-agent-harness`` shorthand expanded through the
   ``src/myrm_agent_harness/`` package prefix;
3. module shortcuts whose first segment is a harness top-level module directory
   (``agent/``, ``toolkits/``, ...) — against the md directory, then the
   package root ``src/myrm_agent_harness/``, then the ``tests/`` mirror tree.

Symbol suffixes (``pkg/mod.attr``, ``path/::member``, trailing CamelCase class
names) are stripped so only the path prefix is verified. Non-path spans (IP
ranges, API routes, timezones, env vars, globs) are skipped. Docs whose refs
carry planning semantics (e.g. competitor benchmark tables) are exempted via
``_MD_REF_SKIP_FILES``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PKG_REL = "src/myrm_agent_harness"
_HARNESS_PKG_PREFIX = _PKG_REL

# Backtick-wrapped code spans that may carry file paths.
_MD_REF_RE = re.compile(r"`([^`\n]+)`")
_MD_SKIP_PREFIXES = (
    "http://",
    "https://",
    "ftp://",
    "www.",
    "/",  # absolute system paths
    "~",  # home-relative
    "$",  # shell/variable expansion
    "{",  # template/glob braces
    "<",  # angle-bracket refs (e.g. docs-placeholder)
)
_MD_SKIP_CHARS = frozenset(" \t*?[]{}<>")
_MD_TRAILING_PUNCT = ".,;:!?)]}>'\""
_FILE_EXTENSIONS = frozenset(
    {".py", ".md", ".ts", ".tsx", ".mjs", ".js", ".cjs", ".sh", ".json", ".yaml", ".yml", ".toml"}
)
# Repo aliases resolved against the monorepo root.
_REPO_ALIAS_DIRS = frozenset({"myrm-agent", "myrm-agent-harness", "myrm-control-plane", "myrm-agent-brand"})
_SUBREPO_ALIASES = {
    "myrm-agent-server": "myrm-agent/myrm-agent-server",
    "myrm-agent-frontend": "myrm-agent/myrm-agent-frontend",
    "myrm-agent-desktop": "myrm-agent/myrm-agent-desktop",
}
# Directories whose .md are runtime/packaging artifacts, not source refs.
_MD_SKIP_DIR_NAMES = frozenset({"prebuilt_skills"})
# Docs whose backtick refs carry planning/benchmark semantics (competitor
# comparison tables) rather than assertions about existing files.
_MD_REF_SKIP_FILES = frozenset({"src/myrm_agent_harness/agent/skills/SKILL_SYSTEM.md"})
_PRUNE_DIR_NAMES = frozenset({"__pycache__", "node_modules", ".git", ".venv", ".mypy_cache", ".myrm"})


@dataclass(frozen=True)
class MdRefReport:
    md_path: Path
    broken_refs: tuple[tuple[str, int], ...]  # (unresolved reference, 1-based line)


def _top_level_module_dirs(repo_root: Path) -> frozenset[str]:
    """Top-level package directories under ``src/myrm_agent_harness/``.

    These are the prefixes docs use when naming module shortcuts without a
    ``./`` (``agent/hooks/...``, ``toolkits/errors/...``)."""
    pkg = repo_root / _PKG_REL
    if not pkg.is_dir():
        return frozenset()
    return frozenset(p.name for p in pkg.iterdir() if p.is_dir())


def _has_env_var_segment(ref: str) -> bool:
    return any(seg.isupper() and "_" in seg for seg in ref.split("/"))


def _is_symbol_suffix(ref: str) -> bool:
    """True when the final segment names a symbol, not a file: ``pkg/mod.attr``,
    ``path/::member``, or a trailing CamelCase class name."""
    last = ref.rsplit("/", 1)[-1]
    if "::" in last:
        return True
    if "." in last and not last.endswith(tuple(_FILE_EXTENSIONS)):
        return True
    return bool(last.isidentifier() and last[0].isupper())


def _strip_symbol_suffix(ref: str) -> str:
    """Reduce a module-attr / member ref to its verifiable path prefix."""
    last = ref.rsplit("/", 1)[-1]
    if "::" in last:
        return ref.split("::", 1)[0].rstrip("/")
    if "." in last and not last.endswith(tuple(_FILE_EXTENSIONS)):
        return ref.rsplit(".", 1)[0]
    if last.isidentifier() and last[0].isupper():
        return ref.rsplit("/", 1)[0]
    return ref


def _is_verifiable_ref(ref: str, top_dirs: frozenset[str]) -> bool:
    """Only semantically explicit refs are checked: ./ ../ relatives, cross-repo
    aliases, or module shortcuts under a known harness top-level directory."""
    if ref.startswith(("./", "../")):
        return True
    first = ref.split("/", 1)[0]
    return first in _REPO_ALIAS_DIRS or first in _SUBREPO_ALIASES or first in top_dirs


def _path_exists(base: Path, ref: str) -> bool:
    """Check a file, a bare module name (``mod`` -> ``mod.py`` / ``mod/``), or
    a package directory (``pkg/mod`` -> ``pkg/mod/__init__.py``)."""
    if (base / ref).exists():
        return True
    if (base / f"{ref}.py").exists():
        return True
    return (base / ref / "__init__.py").exists()


def _extract_md_refs(md_path: Path, repo_root: Path = _REPO_ROOT) -> list[tuple[str, int, str | None]]:
    """Extract backtick path candidates that carry a directory separator.

    For table rows whose first cell is a backticked directory (e.g.
    ``| `docker/` | ... ``), that directory is returned as ``row_dir`` so
    cell refs can be resolved relative to it before falling back to the md."""
    top_dirs = _top_level_module_dirs(repo_root)
    refs: list[tuple[str, int, str | None]] = []
    for line_no, line in enumerate(md_path.read_text(encoding="utf-8").splitlines(), start=1):
        row_dir: str | None = None
        stripped = line.lstrip()
        if stripped.startswith("|"):
            first_cell = _MD_REF_RE.search(stripped)
            if first_cell and first_cell.group(1).strip().endswith("/"):
                row_dir = first_cell.group(1).strip().rstrip("/")
        for match in _MD_REF_RE.finditer(line):
            ref = match.group(1).strip()
            if "/" not in ref:
                continue
            if "://" in ref or "..." in ref:  # URI scheme or path elision
                continue
            if any(ref.startswith(prefix) for prefix in _MD_SKIP_PREFIXES):
                continue
            if ref.startswith(".") and not ref.startswith(("./", "../")):
                continue  # dotfile / single-dot refs
            if _MD_SKIP_CHARS.intersection(ref):
                continue
            cleaned = ref.rstrip(_MD_TRAILING_PUNCT)
            if not cleaned:
                continue
            if _has_env_var_segment(cleaned):
                continue
            if not _is_verifiable_ref(cleaned, top_dirs):
                continue
            cleaned = _strip_symbol_suffix(cleaned)
            if not cleaned or "/" not in cleaned:
                continue
            refs.append((cleaned, line_no, row_dir))
    return refs


def _resolve_md_ref(
    md_path: Path,
    ref: str,
    row_dir: str | None,
    root: Path,
    monorepo_root: Path,
    repo_root: Path,
) -> bool:
    """Resolve a markdown path ref in the order described by the module docstring.
    Cross-repo refs whose repo dir is absent locally (standalone harness) are
    treated as unverifiable and skipped, keeping false positives at zero."""
    if ref.startswith(("./", "../")):
        if _path_exists(md_path.parent, ref):
            return True
        if row_dir is not None and _path_exists(md_path.parent / row_dir, ref):
            return True
        return False
    first = ref.split("/", 1)[0]
    if first in _REPO_ALIAS_DIRS or first in _SUBREPO_ALIASES:
        target_dir = _SUBREPO_ALIASES.get(first, first)
        if not (monorepo_root / target_dir).is_dir():
            return True  # repo not checked out locally; unverifiable
        rest = ref.split("/", 1)[1]
        if _path_exists(monorepo_root / target_dir, rest):
            return True
        if first == "myrm-agent-harness":
            return _path_exists(monorepo_root / target_dir / _HARNESS_PKG_PREFIX, rest)
        return False
    # Module shortcut: md directory -> package root -> tests mirror.
    if _path_exists(md_path.parent, ref):
        return True
    if _path_exists(repo_root / _PKG_REL, ref):
        return True
    return _path_exists(repo_root / "tests", ref)


def scan_md_refs(root: Path, monorepo_root: Path, repo_root: Path) -> list[MdRefReport]:
    reports: list[MdRefReport] = []
    for md in sorted(root.rglob("*.md")):
        if any(part in _PRUNE_DIR_NAMES for part in md.parts):
            continue
        if _MD_SKIP_DIR_NAMES.intersection(md.parts):
            continue
        try:
            rel = md.relative_to(repo_root).as_posix()
        except ValueError:
            rel = str(md)
        if rel in _MD_REF_SKIP_FILES:
            continue
        refs = _extract_md_refs(md, repo_root)
        if not refs:
            continue
        broken = tuple(
            (ref, line_no)
            for ref, line_no, row_dir in refs
            if not _resolve_md_ref(md, ref, row_dir, root, monorepo_root, repo_root)
        )
        if broken:
            reports.append(MdRefReport(md_path=md, broken_refs=broken))
    return reports

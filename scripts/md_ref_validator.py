#!/usr/bin/env python3
"""Validate markdown path references across a repo tree.

Two reference syntaxes are checked: backtick code spans (``path``) and inline
links (``[label](path)``). Backtick spans must carry a directory separator to
count, but an inline link is validated whenever it carries a file extension
even without a separator — ``[guide](other.md)`` resolves against the md's own
directory. Spans that carry a directory separator are resolved for existence in
a deterministic order:

1. explicit relatives (``./`` / ``../``) — against the md file's directory,
   plus the table row's first-cell directory when present;
2. cross-repo aliases (``myrm-agent-server/...`` etc.) — against the monorepo
   root, with the ``myrm-agent-harness`` shorthand expanded through the
   ``src/myrm_agent_harness/`` package prefix;
3. module shortcuts whose first segment is a top-level module directory of the
   scanned repo's source root (harness ``agent/``/``toolkits/``..., server
   ``api/``/``services/``...) — against the md directory, then the package
   root, then the ``tests/`` mirror tree. The source root is the harness
   package for harness scans and is auto-detected (``app/``) for
   ``myrm-agent-server``.

Symbol suffixes (``pkg/mod.attr``, ``path/::member``, trailing CamelCase class
names) are handled by progressive resolution: the full span is tried first,
then trailing dotted attributes are stripped one segment at a time, so a real
file like ``assets/ad_domains.txt`` or ``docker/Dockerfile.official`` resolves
before any stripping is attempted. Non-path spans (IP ranges, API routes,
timezones, env vars, globs) are skipped. Docs whose refs carry planning
semantics (e.g. competitor benchmark tables) are exempted via
``_MD_REF_SKIP_FILES``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PKG_REL = "src/myrm_agent_harness"
# Alternate package root names probed for non-harness repos (server: ``app/``).
# Frontend TS/TSX docs are intentionally not shortcut-scanned: their backtick
# refs mix extension-less imports, barrel paths, and prefix-less cross-repo
# server paths (``app/...``), which this validator cannot resolve reliably
# without false positives; only explicit relatives and aliases apply there.
_PKG_ROOT_CANDIDATES = ("app",)

# Backtick-wrapped code spans that may carry file paths.
_MD_REF_RE = re.compile(r"`([^`\n]+)`")
# Inline links ``[label](target)`` — the leading ``!`` (image) is optional; the
# target stops at the first ``)`` and never spans lines. Link targets carry the
# same path semantics as backtick spans, so both feed one resolution pipeline.
_MD_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
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
# Characters that mark a span as non-path noise. Kept out of the set: ``[``/``]``
# so dynamic path segments (``app/mobile/[chatId]/page.tsx``) still resolve.
_MD_SKIP_CHARS = frozenset(" \t*?{}<>,")
_MD_TRAILING_PUNCT = ".,;:!?)]}>'\""
_FILE_EXTENSIONS = frozenset(
    {".py", ".md", ".ts", ".tsx", ".mjs", ".js", ".cjs", ".sh", ".json", ".yaml", ".yml", ".toml"}
)
# Extension-less refs are probed against these source extensions (frontend refs
# like ``./useMessageQueue`` map to ``useMessageQueue.ts``); Python probing
# (``mod`` -> ``mod.py``) is handled separately in ``_path_exists``.
_PROBE_EXTENSIONS = (".tsx", ".ts", ".mjs", ".js", ".cjs")
# Data file extensions commonly backticked in docs; treated as file refs, not
# dotted symbol suffixes.
_DATA_EXTENSIONS = frozenset({".txt", ".jsonl", ".ndjson", ".csv", ".tsv", ".lock", ".env"})
_FILE_SUFFIXES = _FILE_EXTENSIONS | _DATA_EXTENSIONS
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
# comparison tables, candidate-placement verdicts) rather than assertions about
# existing files.
_MD_REF_SKIP_FILES = frozenset(
    {
        "src/myrm_agent_harness/agent/skills/SKILL_SYSTEM.md",
        "src/myrm_agent_harness/eval/_ARCH.md",
    }
)
PRUNE_DIR_NAMES = frozenset({"__pycache__", "node_modules", ".git", ".venv", ".mypy_cache", ".myrm", "external_reference_project"})


@dataclass(frozen=True)
class MdRefReport:
    md_path: Path
    broken_refs: tuple[tuple[str, int], ...]  # (unresolved reference, 1-based line)


def _discover_pkg_root(root: Path) -> Path | None:
    """Best-effort source-root detection for a non-harness repo scan.

    ``myrm-agent-server`` keeps its package under ``app/``; when ``root`` is
    itself a package root (``app/``, ``myrm_agent_harness/``) it is returned
    as-is."""
    if (root / _PKG_REL).is_dir():
        return root / _PKG_REL
    for rel in _PKG_ROOT_CANDIDATES:
        if (root / rel).is_dir():
            return root / rel
    if root.name in {"app", "myrm_agent_harness"}:
        return root
    return None


def _resolve_pkg_root(root: Path, repo_root: Path) -> Path | None:
    """Package source root for the scanned tree.

    Harness scans (any subtree of ``repo_root``) resolve against the harness
    package; other repos are detected from the scanned ``root`` itself."""
    if root.is_relative_to(repo_root):
        pkg = repo_root / _PKG_REL
        if pkg.is_dir():
            return pkg
    return _discover_pkg_root(root)


def _top_level_module_dirs(pkg_root: Path) -> frozenset[str]:
    """Top-level package directories used as module-shortcut prefixes.

    Cache/artifact dirs are excluded so they are never recognized as module
    shortcuts."""
    skip = {"__pycache__"}
    return frozenset(p.name for p in pkg_root.iterdir() if p.is_dir() and p.name not in skip)


def _has_env_var_segment(ref: str) -> bool:
    return any(seg.isupper() and "_" in seg for seg in ref.split("/"))


def _progressive_paths(ref: str) -> list[str]:
    """Return the ref plus progressively stripped attribute suffixes.

    Handles ``::`` members (``path/utils::is_timeout_error``), dotted chains
    (``toolkits/mcp/schema.normalize.canonicalize``), and trailing CamelCase
    class names (``agent/.../broadcast/ToolBroadcastBus``). Real files whose
    names contain dots (``assets/ad_domains.txt``, ``docker/Dockerfile.official``)
    are tried first and resolve unchanged."""
    paths = [ref]
    head = ref
    if "::" in head:
        head = head.split("::", 1)[0].rstrip("/")
        if head:
            paths.append(head)
    while "/" in head:
        last = head.rsplit("/", 1)[-1]
        if not last:
            break
        if last in {".", ".."}:
            break  # never strip parent-directory markers; ``../..`` is not a symbol
        if last.endswith(tuple(_FILE_SUFFIXES)):
            break
        if "." in last:
            head = head.rsplit(".", 1)[0]
        elif last.isidentifier() and last[0].isupper():
            head = head.rsplit("/", 1)[0]
        else:
            break
        if not head or "/" not in head:
            break
        if head.rsplit("/", 1)[-1] in {".", ".."}:
            break  # a stripped head must remain a real path, not ``../..``
        paths.append(head)
    return paths


def _is_verifiable_ref(ref: str, top_dirs: frozenset[str]) -> bool:
    """Only semantically explicit refs are checked: ./ ../ relatives, cross-repo
    aliases, or module shortcuts under a known harness top-level directory."""
    if ref.startswith(("./", "../")):
        return True
    first = ref.split("/", 1)[0]
    return first in _REPO_ALIAS_DIRS or first in _SUBREPO_ALIASES or first in top_dirs


def _path_exists(base: Path, ref: str) -> bool:
    """Check a file, a bare module name (``mod`` -> ``mod.py`` / ``mod/``), or
    a package directory (``pkg/mod`` -> ``pkg/mod/__init__.py``). A trailing
    slash (``pkg/mod/``) is tolerated for file refs. Extension-less refs are
    also probed against TS/JS source extensions so frontend refs written in
    import notation (``./useMessageQueue``) resolve to their real file."""
    ref = ref.rstrip("/")
    candidates = [ref, f"{ref}.py", f"{ref}/__init__.py"]
    if not Path(ref).suffix:
        candidates.extend(f"{ref}{ext}" for ext in _PROBE_EXTENSIONS)
    return any((base / cand).exists() for cand in candidates)


def _clean_ref(raw: str) -> str | None:
    """Normalize a raw backtick span or link target into a verifiable ref.

    Returns ``None`` when the candidate is not a path we can check (non-path
    span, URL, anchor-only, templated, elided). The ``#fragment`` anchor is
    dropped so ``docs/x.md#section`` resolves against ``docs/x.md``."""
    ref = raw.strip()
    if "://" in ref or "..." in ref:  # URI scheme or path elision
        return None
    if any(ref.startswith(prefix) for prefix in _MD_SKIP_PREFIXES):
        return None
    if ref.startswith(".") and not ref.startswith(("./", "../")):
        return None  # dotfile / single-dot refs
    ref = ref.split("#", 1)[0]
    if not ref:
        return None  # anchor-only link (``[x](#top)``)
    if _MD_SKIP_CHARS.intersection(ref):
        return None
    cleaned = ref.rstrip(_MD_TRAILING_PUNCT)
    if not cleaned:
        return None
    if _has_env_var_segment(cleaned):
        return None
    return cleaned


def _extract_md_refs(md_path: Path, top_dirs: frozenset[str]) -> list[tuple[str, int, str | None]]:
    """Extract path candidates from backtick spans and inline links.

    Both ``path``-style code spans and ``[label](path)`` links feed the same
    filter, so a separated link target is validated exactly like a backticked
    ref. Inline links get one extra rule: a bare leaf filename that carries a
    file extension (``[guide](other.md)``) is validated against the md's
    directory too, whereas the backtick branch keeps the ``/`` requirement so a
    prose mention such as ``main.py`` is not mistaken for a path. Link syntax
    written inside a code span (documentation of the syntax itself) is literal
    text and is not treated as a navigation target. ``top_dirs`` are the harness
    top-level module directories used to recognize module-shortcut refs; pass an
    empty set to restrict validation to explicit relatives and cross-repo
    aliases.

    For table rows whose first cell is a backticked directory (e.g.
    ``| `docker/` | ... ``), that directory is returned as ``row_dir`` so
    cell refs can be resolved relative to it before falling back to the md."""
    refs: list[tuple[str, int, str | None]] = []
    try:
        text = md_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        # Non-UTF-8 or unreadable markdown (fixtures, binary-ish dumps) carries
        # no verifiable refs; skip it instead of aborting the whole scan.
        return refs
    for line_no, line in enumerate(text.splitlines(), start=1):
        row_dir: str | None = None
        symbolic_row = False
        stripped = line.lstrip()
        if stripped.startswith("|"):
            cells = stripped.split("|")
            if len(cells) >= 2:
                first_cell = _MD_REF_RE.search(cells[1])
                if first_cell:
                    cell = first_cell.group(1).strip()
                    if "{" in cell:
                        # Placeholder-anchored rows (``| `sections/{group}/X.tsx` ...``)
                        # are illustrative patterns, not assertions about specific
                        # files, so their refs are not existence-checked.
                        symbolic_row = True
                    elif cell.endswith("/"):
                        row_dir = cell.rstrip("/")
                    elif cell.endswith(tuple(_FILE_SUFFIXES)) and "/" in cell:
                        # Import-specifier tables anchor refs to the first cell's
                        # source file (``| `sections/{g}/X.tsx` | ... | `../Y` |``).
                        # The cell path is source-tree-relative, so strip the
                        # segment matching the md's own directory before resolving
                        # cell refs relative to that source file's directory.
                        cell_dir = cell.rsplit("/", 1)[0]
                        prefix = f"{md_path.parent.name}/"
                        row_dir = cell_dir[len(prefix) :] if cell_dir.startswith(prefix) else cell_dir
        if symbolic_row:
            continue
        for match in _MD_REF_RE.finditer(line):
            cleaned = _clean_ref(match.group(1))
            if cleaned is None or "/" not in cleaned:
                continue
            if not _is_verifiable_ref(cleaned, top_dirs):
                continue
            refs.append((cleaned, line_no, row_dir))
        # Link syntax inside a code span is literal text (docs that document the
        # syntax itself), so blank out code spans before scanning links to avoid
        # validating it as a navigation target.
        link_source = _MD_REF_RE.sub(lambda m: " " * len(m.group(0)), line)
        for match in _MD_LINK_RE.finditer(link_source):
            cleaned = _clean_ref(match.group(1))
            if cleaned is None:
                continue
            if "/" in cleaned:
                if not _is_verifiable_ref(cleaned, top_dirs):
                    continue
            elif not cleaned.lower().endswith(tuple(_FILE_SUFFIXES)):
                # A bare label carrying no file extension is prose (``#anchor``
                # targets were already dropped by ``_clean_ref``), not a path.
                continue
            # Inline links are explicit navigation targets, so a bare leaf
            # filename (``[guide](other.md)``) is validated against the md's
            # own directory. Backtick prose deliberately keeps the top-dir
            # gate above, which would otherwise flag every ``main.py`` mention.
            refs.append((cleaned, line_no, row_dir))
    return refs


def _resolve_md_ref(
    md_path: Path,
    ref: str,
    row_dir: str | None,
    monorepo_root: Path,
    repo_root: Path,
    pkg_root: Path | None,
) -> bool:
    """Resolve a markdown path ref in the order described by the module docstring.
    Cross-repo refs whose repo dir is absent locally (standalone harness) are
    treated as unverifiable and skipped, keeping false positives at zero."""
    for cand in _progressive_paths(ref):
        if cand.startswith(("./", "../")):
            if _path_exists(md_path.parent, cand):
                return True
            if row_dir is not None and _path_exists(md_path.parent / row_dir, cand):
                return True
            continue
        first = cand.split("/", 1)[0]
        if first in _REPO_ALIAS_DIRS or first in _SUBREPO_ALIASES:
            target_dir = _SUBREPO_ALIASES.get(first, first)
            if not (monorepo_root / target_dir).is_dir():
                return True  # repo not checked out locally; unverifiable
            rest = cand.split("/", 1)[1]
            if _path_exists(monorepo_root / target_dir, rest):
                return True
            if first == "myrm-agent-harness" and _path_exists(
                monorepo_root / target_dir / _PKG_REL, rest
            ):
                return True
            continue
        # Module shortcut: md directory -> package root -> tests mirror.
        if _path_exists(md_path.parent, cand):
            return True
        if pkg_root is not None and _path_exists(pkg_root, cand):
            return True
        if _path_exists(repo_root / "tests", cand):
            return True
    return False


def scan_md_refs(root: Path, monorepo_root: Path, repo_root: Path) -> list[MdRefReport]:
    """Scan ``*.md`` under ``root`` for unresolved path refs.

    Module-shortcut resolution (``agent/hooks/...``) applies to harness docs via
    the harness top-level module dirs; ``myrm-agent-server`` derives its own
    source root (``app/``) from the scanned ``root``."""
    pkg_root = _resolve_pkg_root(root, repo_root)
    top_dirs = _top_level_module_dirs(pkg_root) if pkg_root is not None else frozenset()
    reports: list[MdRefReport] = []
    for md in sorted(root.rglob("*.md")):
        if any(part in PRUNE_DIR_NAMES for part in md.parts):
            continue
        if _MD_SKIP_DIR_NAMES.intersection(md.parts):
            continue
        try:
            rel = md.relative_to(repo_root).as_posix()
        except ValueError:
            rel = str(md)
        if rel in _MD_REF_SKIP_FILES:
            continue
        refs = _extract_md_refs(md, top_dirs)
        if not refs:
            continue
        broken = tuple(
            (ref, line_no)
            for ref, line_no, row_dir in refs
            if not _resolve_md_ref(md, ref, row_dir, monorepo_root, repo_root, pkg_root)
        )
        if broken:
            reports.append(MdRefReport(md_path=md, broken_refs=broken))
    return reports

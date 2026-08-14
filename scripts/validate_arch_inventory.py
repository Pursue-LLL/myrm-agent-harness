#!/usr/bin/env python3
"""Validate module-level _ARCH.md file tables and markdown path references.

Two independent checks:

1. **_ARCH inventory** — module-level ``_ARCH.md`` file tables must list sibling
   ``.py`` files (bidirectional: every py file listed, every listed py on disk).
2. **markdown path refs** (``--md-refs``) — backtick-wrapped relative paths in
   any ``*.md`` under the scanned root must resolve to a real file/directory
   (relative to the md file, to a known repo alias, or to the monorepo root).

Only parses markdown **table rows** (lines starting with ``|``) in ``_ARCH.md`` —
prose mentions of ``other_module.py`` are ignored by check 1; check 2 also scans
prose so that refactor-orphaned paths surface in CI.

Usage:
    python scripts/validate_arch_inventory.py
    python scripts/validate_arch_inventory.py --root src/myrm_agent_harness
    python scripts/validate_arch_inventory.py --root src/myrm_agent_harness/agent
    python scripts/validate_arch_inventory.py --md-refs
    python scripts/validate_arch_inventory.py --json

Exit codes:
    0: All checked directories consistent
    1: Missing/stale _ARCH entries or broken markdown path refs detected
    2: Internal error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MONOREPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TABLE_HEADER_CELLS = frozenset({"File", "Module", "Submodule", "文件"})
_PRUNE_DIR_NAMES = frozenset({"__pycache__", "node_modules", ".git", ".venv", ".mypy_cache", ".myrm"})

# Backtick-wrapped code spans that may carry file paths (``[^\n`]+``).
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
# Repo alias dirs resolved against the monorepo root (open-perplexity/).
_REPO_ALIAS_DIRS = frozenset({"myrm-agent", "myrm-agent-harness", "myrm-control-plane", "myrm-agent-brand"})
# Sub-repo aliases map to their actual monorepo-relative location.
_SUBREPO_ALIASES = {
    "myrm-agent-server": "myrm-agent/myrm-agent-server",
    "myrm-agent-frontend": "myrm-agent/myrm-agent-frontend",
    "myrm-agent-desktop": "myrm-agent/myrm-agent-desktop",
}
# Docs commonly refer to harness modules by dropping the package prefix
# (e.g. `myrm-agent-harness/toolkits/...` vs `src/myrm_agent_harness/toolkits/...`).
_HARNESS_PKG_PREFIX = "src/myrm_agent_harness"
# Directories whose .md are runtime/packaging artifacts, not source refs.
_MD_SKIP_DIR_NAMES = frozenset({"prebuilt_skills"})


@dataclass(frozen=True)
class DirReport:
    directory: Path
    py_files: tuple[str, ...]
    arch_path: Path
    listed: frozenset[str]
    missing_in_arch: tuple[str, ...]
    extra_in_arch: tuple[str, ...]


@dataclass(frozen=True)
class MdRefReport:
    md_path: Path
    broken_refs: tuple[tuple[str, int], ...]  # (unresolved reference, 1-based line)


def _collect_py_files(directory: Path) -> list[str]:
    return sorted(
        p.name
        for p in directory.iterdir()
        if p.is_file() and p.suffix == ".py"
    )


def _first_table_cell(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = [cell.strip() for cell in stripped.split("|")]
    if len(cells) < 3:
        return None
    return cells[1].strip("`").strip()


def _is_inventory_file_cell(first: str) -> bool:
    """Return True when the first table cell names a single sibling .py file."""
    if first == "__init__.py":
        return True
    if not first.endswith(".py"):
        return False
    if "/" in first or "\\" in first:
        return False
    # Comparison/prose rows often list multiple paths in one cell.
    if "," in first:
        return False
    stem = first[: -len(".py")]
    return stem.isidentifier()


def _listed_py_in_arch(arch_path: Path) -> set[str]:
    listed: set[str] = set()
    for line in arch_path.read_text(encoding="utf-8").splitlines():
        first = _first_table_cell(line)
        if first is None:
            continue
        if first in _TABLE_HEADER_CELLS:
            continue
        if first.startswith("---") or first.startswith("—"):
            continue
        if _is_inventory_file_cell(first):
            listed.add(first)
    return listed


def scan_directory(directory: Path) -> DirReport | None:
    arch_path = directory / "_ARCH.md"
    if not arch_path.is_file():
        return None
    py_files = _collect_py_files(directory)
    listed = _listed_py_in_arch(arch_path)
    py_set = set(py_files)
    missing = tuple(sorted(py_set - listed))
    extra = tuple(sorted(listed - py_set))
    return DirReport(
        directory=directory,
        py_files=tuple(py_files),
        arch_path=arch_path,
        listed=frozenset(listed),
        missing_in_arch=missing,
        extra_in_arch=extra,
    )


def scan_tree(root: Path) -> list[DirReport]:
    reports: list[DirReport] = []
    for arch in sorted(root.rglob("_ARCH.md")):
        if any(part in _PRUNE_DIR_NAMES for part in arch.parts):
            continue
        report = scan_directory(arch.parent)
        if report is not None and report.py_files:
            reports.append(report)
    return reports


def _is_symbol_ref(ref: str) -> bool:
    """True for module-attr references like `pkg/mod.attr` or `pkg/sub.mod.fn`."""
    last = ref.rsplit("/", 1)[-1]
    if "." not in last:
        return False
    return not last.endswith(tuple(_FILE_EXTENSIONS))


def _has_env_var_segment(ref: str) -> bool:
    return any(seg.isupper() and "_" in seg for seg in ref.split("/"))


def _is_verifiable_ref(ref: str) -> bool:
    """Only semantically explicit refs are checked: ./ and ../ relatives, or
    cross-repo refs with a known repo alias prefix. Ambiguous prose paths
    (module shortcuts like `middlewares/x.py`) are intentionally not verified."""
    if ref.startswith(("./", "../")):
        return True
    first = ref.split("/", 1)[0]
    return first in _REPO_ALIAS_DIRS or first in _SUBREPO_ALIASES


def _extract_md_refs(md_path: Path) -> list[tuple[str, int, str | None]]:
    """Extract backtick path candidates that carry a directory separator.

    For table rows whose first cell is a backticked directory (e.g.
    ``| `docker/` | ... ``), that directory is returned as ``row_dir`` so
    cell refs can be resolved relative to it before falling back to the md."""
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
            if not _is_verifiable_ref(cleaned):
                continue
            if _is_symbol_ref(cleaned) or _has_env_var_segment(cleaned):
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
    """Resolve an explicit markdown path ref: ./ ../ relatives resolve against
    the md's directory (and, for table rows, the row's first-cell directory);
    cross-repo refs resolve against the monorepo root. Cross-repo refs whose
    repo dir is absent locally (standalone harness) are treated as unverifiable
    and skipped, keeping false positives at zero."""
    if ref.startswith(("./", "../")):
        if (md_path.parent / ref).exists():
            return True
        if row_dir is not None and (md_path.parent / row_dir / ref).exists():
            return True
        return (md_path.parent / f"{ref}.py").exists()  # module ref without extension
    first = ref.split("/", 1)[0]
    target_dir = _SUBREPO_ALIASES.get(first, first)
    if not (monorepo_root / target_dir).is_dir():
        return True  # repo not checked out locally; unverifiable
    rest = ref.split("/", 1)[1]
    if (monorepo_root / target_dir / rest).exists():
        return True
    if first == "myrm-agent-harness":
        return (monorepo_root / target_dir / _HARNESS_PKG_PREFIX / rest).exists()
    return False


def scan_md_refs(root: Path, monorepo_root: Path, repo_root: Path) -> list[MdRefReport]:
    reports: list[MdRefReport] = []
    for md in sorted(root.rglob("*.md")):
        if any(part in _PRUNE_DIR_NAMES for part in md.parts):
            continue
        if _MD_SKIP_DIR_NAMES.intersection(md.parts):
            continue
        refs = _extract_md_refs(md)
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


def _rel_to_repo(path: Path) -> Path:
    try:
        return path.relative_to(_REPO_ROOT)
    except ValueError:
        return path


def _format_reports(reports: list[DirReport], *, root_label: str) -> str:
    lines = ["=" * 72, f"_ARCH.md inventory validation ({root_label})", "=" * 72]
    failed = False
    for report in reports:
        rel = _rel_to_repo(report.directory)
        if report.missing_in_arch or report.extra_in_arch:
            failed = True
            lines.append(f"\nFAIL {rel}")
            if report.missing_in_arch:
                lines.append(f"  missing in _ARCH: {', '.join(report.missing_in_arch)}")
            if report.extra_in_arch:
                lines.append(f"  listed but not on disk: {', '.join(report.extra_in_arch)}")
        else:
            lines.append(f"OK   {rel} ({len(report.py_files)} py files)")
    lines.append("")
    lines.append("PASS" if not failed else "FAIL - fix _ARCH.md file tables")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate _ARCH.md py file inventories")
    parser.add_argument(
        "--root",
        type=Path,
        default=_REPO_ROOT / "src" / "myrm_agent_harness",
        help="Package subtree to scan (default: entire src/myrm_agent_harness/)",
    )
    parser.add_argument(
        "--md-refs",
        action="store_true",
        help="Also validate backtick path references in *.md under the root",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2

    # The _ARCH.md table inventory reflects this repo's own table convention
    # (harness lists __init__.py; other repos generate tables differently), so
    # table validation only applies inside the harness repo. Cross-repo scans
    # are supported exclusively for markdown path reference validation.
    scan_tables = root.is_relative_to(_REPO_ROOT)
    if not scan_tables and not args.md_refs:
        print(f"ERROR: table inventory validation only supports roots inside {_REPO_ROOT}", file=sys.stderr)
        return 2

    reports = scan_tree(root) if scan_tables else []
    has_fail = any(r.missing_in_arch or r.extra_in_arch for r in reports)

    md_reports: list[MdRefReport] = []
    if args.md_refs:
        md_reports = scan_md_refs(root, _MONOREPO_ROOT, _REPO_ROOT)
        has_fail = has_fail or bool(md_reports)

    if args.json:
        payload = [
            {
                "directory": str(_rel_to_repo(r.directory)),
                "py_files": list(r.py_files),
                "missing_in_arch": list(r.missing_in_arch),
                "extra_in_arch": list(r.extra_in_arch),
            }
            for r in reports
        ]
        if args.md_refs:
            payload.append(
                {
                    "md_refs": [
                        {
                            "md": str(_rel_to_repo(r.md_path)),
                            "broken": [{"ref": ref, "line": line} for ref, line in r.broken_refs],
                        }
                        for r in md_reports
                    ]
                }
            )
        print(json.dumps({"ok": not has_fail, "reports": payload}, indent=2))
    else:
        root_label = _rel_to_repo(root).as_posix()
        if reports:
            print(_format_reports(reports, root_label=root_label))
        if args.md_refs:
            print("=" * 72)
            if md_reports:
                print("FAIL - broken markdown path references")
                for report in md_reports:
                    rel = _rel_to_repo(report.md_path)
                    for ref, line_no in report.broken_refs:
                        print(f"  {rel}:{line_no}: `{ref}` not found")
            else:
                print(f"PASS - markdown path references resolve ({root_label})")

    return 1 if has_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""CLI entry point for tool-registry consistency enforcement.

Validates that every `@tool` / `BaseTool` subclass / middleware-renamed tool
is registered in the harness `_TOOL_LAYERS` (or in the server bootstrap),
detects orphan tool factories, and regenerates documentation count blocks.

Usage:
    python scripts/validate_tool_registry.py                 # Full scan (CI mode)
    python scripts/validate_tool_registry.py --incremental   # Pre-commit mode
    python scripts/validate_tool_registry.py --generate-docs # Refresh doc count blocks
    python scripts/validate_tool_registry.py --json          # Machine-readable output

Exit codes:
    0: No violations
    1: Inconsistency or orphan detected
    2: Internal error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
_harness_root = _repo_root / "myrm-agent-harness"
sys.path.insert(0, str(_harness_root))

from scripts.tool_registry_config import HARNESS_SRC, SCAN_ROOTS  # noqa: E402
from scripts.tool_registry_engine import (  # noqa: E402
    ScanReport,
    get_changed_python_files,
    load_registered_layers,
    scan,
)

_COUNT_DOC_TARGETS = (
    HARNESS_SRC / "agent" / "tool_management" / "_ARCH.md",
    HARNESS_SRC / "agent" / "tool_management" / "DEFAULT_AGENT_TOKEN_INVENTORY.md",
    HARNESS_SRC / "agent" / "tool_management" / "TOOL_DESIGN_STRATEGY.md",
)
_CATALOG_DOC_TARGET = HARNESS_SRC / "agent" / "tool_management" / "TOOL_MANAGEMENT_SYSTEM.md"

_BLOCK_BEGIN = "<!-- TOOL_COUNT_BEGIN -->"
_BLOCK_END = "<!-- TOOL_COUNT_END -->"
_CATALOG_BEGIN = "<!-- TOOL_CATALOG_BEGIN -->"
_CATALOG_END = "<!-- TOOL_CATALOG_END -->"

_FORBIDDEN_BINDMODE_PATTERNS = (
    re.compile(r"\bget_deferred_tools\b"),
    re.compile(r"\bdeferred_tools\b"),
)
_FORBIDDEN_TERM_SCAN_ROOTS = (
    HARNESS_SRC / "agent",
    _harness_root / "tests" / "agent",
)
_FORBIDDEN_TERM_PATH_EXCLUDES = ("context_management",)


def _scan_forbidden_bindmode_terms() -> list[tuple[Path, int, str]]:
    """Detect legacy deferred API names in agent tool-management code paths."""
    violations: list[tuple[Path, int, str]] = []
    for root in _FORBIDDEN_TERM_SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if any(part in _FORBIDDEN_TERM_PATH_EXCLUDES for part in path.parts):
                continue
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if any(pat.search(line) for pat in _FORBIDDEN_BINDMODE_PATTERNS):
                    violations.append((path, line_no, line.strip()))
    return violations


def _load_registry_metadata_keys() -> set[str]:
    from myrm_agent_harness.core.security.tool_registry import (
        TOOL_CANONICAL_PARAMS,
        TOOL_GROUP_MAP,
        TOOL_PERMISSION_MAP,
        TOOL_SAFETY_METADATA,
    )

    keys: set[str] = set(TOOL_PERMISSION_MAP)
    keys.update(TOOL_CANONICAL_PARAMS)
    keys.update(TOOL_SAFETY_METADATA)
    for tools in TOOL_GROUP_MAP.values():
        keys.update(tools)
    return keys


def _format_report(
    report: ScanReport,
    *,
    incremental: bool = False,
    metadata_ghosts: set[str] | None = None,
) -> str:
    layer_counts = _layer_counts(report)
    lines = [
        "=" * 80,
        "Tool Registry Validation Report" + (" (incremental)" if incremental else ""),
        "=" * 80,
        f"Files scanned: {report.files_scanned}",
        f"Tool declarations found (deduplicated by name): {len(report.declared_names)}",
        f"Registered in _TOOL_LAYERS (harness static + server bootstrap): {len(report.registered_names)}",
        "",
        f"Layer breakdown (registered): CORE={layer_counts['CORE']} COMMON={layer_counts['COMMON']} EXTENDED={layer_counts['EXTENDED']}",
        "",
    ]

    missing = report.missing_registrations()
    duplicates = report.duplicate_declarations()
    ghosts: set[str] = set() if incremental else report.ghost_registrations()
    orphans: set[str] = set() if incremental else report.orphan_factories()
    meta_ghosts: set[str] = set() if incremental else (metadata_ghosts or set())

    if not missing and not ghosts and not orphans and not duplicates and not meta_ghosts:
        lines.append("PASS - tool registry consistent")
        return "\n".join(lines)

    if missing:
        lines.append(f"FAIL - {len(missing)} tool(s) defined but NOT registered in _TOOL_LAYERS:")
        for name in sorted(missing):
            owners = [d for d in report.declarations if d.name == name]
            owner = owners[0]
            lines.append(f"  - {name}  ({owner.kind} @ {owner.file.relative_to(_repo_root)}:{owner.line})")
        lines.append("  Fix: register via `register_tool_layer()` in either tool_layers.py (harness)")
        lines.append("       or _tool_layer_bootstrap.py (server).")
        lines.append("")

    if ghosts:
        lines.append(f"FAIL - {len(ghosts)} tool(s) registered but NO source defines them:")
        for name in sorted(ghosts):
            lines.append(f"  - {name}")
        lines.append("  Fix: remove the dead registration entry.")
        lines.append("")

    if orphans:
        lines.append(f"FAIL - {len(orphans)} tool factory function(s) without any call site:")
        for factory in sorted(orphans):
            origin = report.factories[factory]
            lines.append(f"  - {factory}  (defined @ {origin.relative_to(_repo_root)})")
        lines.append("  Fix: either wire the factory into a startup path, or delete the dead code.")
        lines.append("       To intentionally allow an unused factory, add it to ORPHAN_FACTORY_WHITELIST.")
        lines.append("")

    if meta_ghosts:
        lines.append(
            f"FAIL - {len(meta_ghosts)} registry metadata key(s) with NO @tool source:"
        )
        for name in sorted(meta_ghosts):
            lines.append(f"  - {name}")
        lines.append("  Fix: remove dead keys from tool_registry.py maps or register the tool.")
        lines.append("")

    if duplicates:
        lines.append(f"FAIL - {len(duplicates)} tool name(s) declared in multiple source files:")
        for name in sorted(duplicates):
            lines.append(f"  - {name}")
            for decl in duplicates[name]:
                lines.append(f"      {decl.file.relative_to(_repo_root)}:{decl.line}")
        lines.append("  Fix: rename one of the colliding tools. Identical names would")
        lines.append("       silently overwrite each other in the runtime registry.")
        lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


def _layer_counts(report: ScanReport) -> dict[str, int]:
    """Aggregate layer counts across harness static dict + server bootstrap.

    The bootstrap is parsed via AST so the count is accurate even when
    the server tool layers diverge from harness defaults (e.g., `request_answer_user_tool`
    moves to CORE under server-owned registration).
    """
    counts = Counter(load_registered_layers().values())
    return {
        "CORE": counts.get("CORE", 0),
        "COMMON": counts.get("COMMON", 0),
        "EXTENDED": counts.get("EXTENDED", 0),
    }


def _build_doc_block(report: ScanReport) -> str:
    counts = _layer_counts(report)
    action_total = sum(counts.values())
    from myrm_agent_harness.agent.orchestration.hooks import RUNTIME_HOOK_NAMES
    from myrm_agent_harness.agent.orchestration.signals.catalog import ORCHESTRATION_SIGNAL_NAMES

    return (
        f"{_BLOCK_BEGIN}\n"
        f"LLM tools: **{action_total}** "
        f"(CORE {counts['CORE']} + COMMON {counts['COMMON']} + EXTENDED {counts['EXTENDED']}). "
        f"Orchestration signals: **{len(ORCHESTRATION_SIGNAL_NAMES)}**. "
        f"Runtime hooks: **{len(RUNTIME_HOOK_NAMES)}**. "
        "LLM-tool SSOT: `tool_layers.py` + `_tool_layer_bootstrap.py`. "
        "Control-plane SSOT: `agent/orchestration/`. "
        "Auto-generated by `scripts/validate_tool_registry.py --generate-docs`.\n"
        f"{_BLOCK_END}"
    )


def _build_catalog_block() -> str:
    from myrm_agent_harness.agent.tool_management.tool_catalog import (
        build_tool_catalog_rows,
        format_tool_catalog_markdown,
    )

    registered = load_registered_layers()
    rows = build_tool_catalog_rows(registered)
    table = format_tool_catalog_markdown(rows)
    return (
        f"{_CATALOG_BEGIN}\n"
        "### LLM Tool Catalog (auto-generated)\n\n"
        "Only **LLM tools** (`_TOOL_LAYERS` + ToolRegistry) appear here. "
        "Orchestration signals and runtime hooks live under `agent/orchestration/`.\n\n"
        f"{table}\n"
        f"{_CATALOG_END}"
    )


def _update_doc_blocks(doc_path: Path, blocks: dict[str, str]) -> tuple[bool, str | None]:
    """Update marker blocks. Returns (changed, error_message_if_any)."""
    if not doc_path.exists():
        return False, f"doc target missing: {doc_path}"
    text = doc_path.read_text(encoding="utf-8")
    new_text = text
    changed = False

    for begin, end, block in (
        (_BLOCK_BEGIN, _BLOCK_END, blocks.get("count")),
        (_CATALOG_BEGIN, _CATALOG_END, blocks.get("catalog")),
    ):
        if block is None:
            continue
        if begin not in new_text or end not in new_text:
            return False, f"{doc_path} missing {begin} markers"
        start = new_text.index(begin)
        end_idx = new_text.index(end) + len(end)
        replacement = block
        if new_text[start:end_idx] != replacement:
            new_text = new_text[:start] + replacement + new_text[end_idx:]
            changed = True

    if changed:
        doc_path.write_text(new_text, encoding="utf-8")
    return changed, None


def _update_doc_block(doc_path: Path, block: str) -> tuple[bool, str | None]:
    """Update the count block. Returns (changed, error_message_if_any)."""
    return _update_doc_blocks(doc_path, {"count": block})


def _filter_report_to_files(report: ScanReport, files: set[Path]) -> ScanReport:
    """Down-scope declarations to only the files the user changed.

    `registered_names` stays full so newly-added @tools without registration
    are still detected. Ghost/orphan checks must be suppressed by the CLI
    layer for incremental runs, because they require a global view.
    """
    return ScanReport(
        declarations=[d for d in report.declarations if d.file in files],
        registered_names=report.registered_names,
        factories={n: p for n, p in report.factories.items() if p in files},
        factory_call_sites=report.factory_call_sites,
        files_scanned=len(files),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Tool registry consistency checker")
    parser.add_argument("--incremental", action="store_true", help="Only consider files changed in git")
    parser.add_argument("--generate-docs", action="store_true", help="Refresh TOOL_COUNT blocks in docs")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    try:
        full_report = scan()
    except Exception as exc:
        print(f"Internal error: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 2

    report = full_report
    if args.incremental:
        changed = get_changed_python_files(SCAN_ROOTS)
        if changed:
            report = _filter_report_to_files(full_report, set(changed))

    if args.generate_docs:
        count_block = _build_doc_block(full_report)
        catalog_block = _build_catalog_block()
        modified: list[Path] = []
        doc_errors: list[str] = []
        for target in _COUNT_DOC_TARGETS:
            changed, err = _update_doc_blocks(target, {"count": count_block})
            if changed:
                modified.append(target)
            if err:
                doc_errors.append(err)
        changed, err = _update_doc_blocks(_CATALOG_DOC_TARGET, {"catalog": catalog_block})
        if changed:
            modified.append(_CATALOG_DOC_TARGET)
        if err:
            doc_errors.append(err)
        if doc_errors:
            print("ERROR: --generate-docs cannot update docs:", file=sys.stderr)
            for err in doc_errors:
                print(f"  - {err}", file=sys.stderr)
            print("Add `<!-- TOOL_COUNT_BEGIN -->...<!-- TOOL_COUNT_END -->` markers.", file=sys.stderr)
            return 1
        if modified:
            print("Updated TOOL_COUNT blocks in:")
            for path in modified:
                try:
                    display = path.relative_to(_repo_root)
                except ValueError:
                    display = path
                print(f"  - {display}")
        else:
            print("Docs already up-to-date.")

    missing = report.missing_registrations()
    duplicates = report.duplicate_declarations()
    # Ghost and orphan checks require a global view; suppress them in
    # incremental mode to avoid false positives from filtered declarations.
    ghosts = set() if args.incremental else report.ghost_registrations()
    orphans = set() if args.incremental else report.orphan_factories()
    metadata_ghosts = (
        set()
        if args.incremental
        else report.ghost_registry_metadata_keys(_load_registry_metadata_keys())
    )
    bindmode_violations = [] if args.incremental else _scan_forbidden_bindmode_terms()
    catalog_errors: list[str] = []
    if not args.incremental:
        from myrm_agent_harness.agent.tool_management.tool_catalog import validate_tool_catalog

        catalog_errors = validate_tool_catalog(load_registered_layers())
    fail = bool(
        missing
        or ghosts
        or orphans
        or duplicates
        or metadata_ghosts
        or bindmode_violations
        or catalog_errors
    )

    if args.json:
        payload = {
            "mode": "incremental" if args.incremental else "full",
            "files_scanned": report.files_scanned,
            "declared": sorted(report.declared_names),
            "registered": sorted(report.registered_names),
            "layer_counts": _layer_counts(report),
            "missing": sorted(missing),
            "ghosts": sorted(ghosts),
            "metadata_ghosts": sorted(metadata_ghosts),
            "orphans": sorted(orphans),
            "duplicates": {
                name: [f"{decl.file.relative_to(_repo_root)}:{decl.line}" for decl in decls]
                for name, decls in duplicates.items()
            },
        }
        print(json.dumps(payload, indent=2))
    else:
        print(
            _format_report(
                report,
                incremental=args.incremental,
                metadata_ghosts=metadata_ghosts,
            )
        )
        if bindmode_violations:
            print(f"FAIL - {len(bindmode_violations)} forbidden ToolBindMode legacy term(s):")
            for path, line_no, line in bindmode_violations:
                try:
                    display = path.relative_to(_repo_root)
                except ValueError:
                    display = path
                print(f"  - {display}:{line_no}: {line}")
            print("  Fix: use discoverable_tools / get_discoverable_tools / get_runtime_tools.")
        if catalog_errors:
            print(f"FAIL - {len(catalog_errors)} tool catalog metadata issue(s):")
            for err in catalog_errors:
                print(f"  - {err}")
            print("  Fix: update tool_catalog.py role/load overrides.")

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

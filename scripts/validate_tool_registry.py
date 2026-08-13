#!/usr/bin/env python3
"""CLI entry point for tool-registry consistency enforcement.

Validates that every `@tool` / `BaseTool` subclass / middleware-renamed tool
is registered in the harness `_TOOL_LAYERS` (or in the server bootstrap),
enforces layer-product consistency (COMMON = default-on product IDs),
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

from scripts.tool_registry_config import (  # noqa: E402
    HARNESS_SRC,
    SCAN_ROOTS,
    SERVER_ROOT,
)
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
_CATALOG_DOC_TARGET = (
    HARNESS_SRC / "agent" / "tool_management" / "TOOL_MANAGEMENT_SYSTEM.md"
)

_BLOCK_BEGIN = "<!-- TOOL_COUNT_BEGIN -->"
_BLOCK_END = "<!-- TOOL_COUNT_END -->"
_CATALOG_BEGIN = "<!-- TOOL_CATALOG_BEGIN -->"
_CATALOG_END = "<!-- TOOL_CATALOG_END -->"

_FORBIDDEN_BINDMODE_PATTERNS = (
    re.compile(r"\bget_deferred_tools\b"),
    re.compile(r"\bdeferred_tools\b"),
    re.compile(r"\bdiscoverable_tools\b"),
    re.compile(r"\bget_discoverable_tools\b"),
    re.compile(r"\bToolBindMode\.DISCOVERABLE\b"),
    re.compile(r"\bDISCOVERABLE\s*="),
)
_FORBIDDEN_CATALOG_INVOKE_PATTERNS = (
    re.compile(r"\bcapability_invoke_tool\b"),
    re.compile(r"\bsync_capability_invoke_tool\b"),
    re.compile(r"\bbind_economics\b"),
    re.compile(r"\bCapabilityCatalogMiddleware\b"),
    re.compile(r"\bcatalog_invoke_active\b"),
    re.compile(r"\bCATALOG_INVOKE\b"),
    re.compile(r"\bshould_use_catalog_invoke\b"),
    re.compile(r"\bshould_bind_capability_invoke\b"),
    re.compile(r"\bget_runtime_capability_catalog\b"),
    re.compile(r"\bbuild_runtime_catalog_overlay\b"),
)
_FORBIDDEN_TERM_SCAN_ROOTS = (
    HARNESS_SRC / "agent",
    _harness_root / "tests" / "agent",
    _harness_root / "tests" / "architecture",
)
_FORBIDDEN_TERM_PATH_EXCLUDES = ("context_management",)
_FORBIDDEN_TERM_FILE_EXCLUDES = frozenset(
    {
        "test_mcp_routing_two_outcomes.py",
    }
)


def _scan_forbidden_bindmode_terms() -> list[tuple[Path, int, str]]:
    """Detect legacy deferred API names in agent tool-management code paths."""
    return _scan_forbidden_patterns(_FORBIDDEN_BINDMODE_PATTERNS)


def _scan_forbidden_catalog_invoke_terms() -> list[tuple[Path, int, str]]:
    """Detect removed catalog_invoke / capability_invoke gateway code paths."""
    return _scan_forbidden_patterns(_FORBIDDEN_CATALOG_INVOKE_PATTERNS)


def _scan_forbidden_patterns(
    patterns: tuple[re.Pattern[str], ...],
) -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []
    for root in _FORBIDDEN_TERM_SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if path.name in _FORBIDDEN_TERM_FILE_EXCLUDES:
                continue
            if any(part in _FORBIDDEN_TERM_PATH_EXCLUDES for part in path.parts):
                continue
            for line_no, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if any(pat.search(line) for pat in patterns):
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


# Built-in tools covered by resolve_permission_type() dynamic sub-action branches.
_DYNAMICALLY_RESOLVED_TOOLS: frozenset[str] = frozenset(
    {
        "bash_process_tool",
        "browser_interact_tool",
        "browser_manage_tool",
        "desktop_snapshot_tool",
        "desktop_interact_tool",
        "desktop_vision_tool",
    }
)

# Management/delegation/scheduling tools that must declare TOOL_CANONICAL_PARAMS
# so allow-always hashing stays precise (full-arg hashing would break matching).
_CANONICAL_REQUIRED_TOOLS: frozenset[str] = frozenset(
    {
        "cron_manage_tool",
        "delegate_task_tool",
        "delegate_to_agent_tool",
        "skill_manage_tool",
        "subagent_control_tool",
    }
)


def _check_governance_coverage() -> tuple[list[str], dict[str, object]]:
    """Validate governance coverage of built-in tools and permission types.

    Fail-closed rules (mirrors the runtime ``resolve_permission_type`` fallback):

    1. Every built-in tool must be covered by an explicit ``TOOL_PERMISSION_MAP``
       entry, a dynamic resolver branch, or an ``AUTO_APPROVED_BUILTIN_TOOLS``
       declaration with a reason from ``AUTO_APPROVE_REASONS``.
    2. Every permission type produced by ``TOOL_PERMISSION_MAP`` must have an
       explicit ``DEFAULT_RULESET`` rule or a ``RULESET_COVERAGE_WHITELIST``
       declaration.
    3. Every built-in tool must declare ``TOOL_SAFETY_METADATA``.
    4. Management/delegation/scheduling tools must declare
       ``TOOL_CANONICAL_PARAMS``.

    Returns ``(errors, coverage_matrix)``; the matrix is a machine-readable
    per-tool / per-permission-type audit table for ``--json`` output.
    """
    from myrm_agent_harness.core.security.tool_registry import (
        AUTO_APPROVED_BUILTIN_TOOLS,
        AUTO_APPROVE_REASONS,
        BUILTIN_TOOL_NAMES,
        RULESET_COVERAGE_WHITELIST,
        TOOL_CANONICAL_PARAMS,
        TOOL_PERMISSION_MAP,
        TOOL_SAFETY_METADATA,
    )
    from myrm_agent_harness.core.security.types import DEFAULT_RULESET

    errors: list[str] = []

    uncovered_tools: list[str] = []
    ghost_declarations: list[str] = []
    invalid_reasons: list[str] = []
    for tool in sorted(BUILTIN_TOOL_NAMES):
        if tool in TOOL_PERMISSION_MAP or tool in _DYNAMICALLY_RESOLVED_TOOLS:
            continue
        reason = AUTO_APPROVED_BUILTIN_TOOLS.get(tool)
        if reason is None:
            uncovered_tools.append(tool)

    for tool, reason in sorted(AUTO_APPROVED_BUILTIN_TOOLS.items()):
        if tool not in BUILTIN_TOOL_NAMES:
            ghost_declarations.append(tool)
        if reason not in AUTO_APPROVE_REASONS:
            invalid_reasons.append(f"{tool}={reason!r}")

    if uncovered_tools:
        errors.append(
            "Built-in tool(s) without permission mapping, dynamic resolution, or "
            "AUTO_APPROVED_BUILTIN_TOOLS declaration (governance fail-closed): "
            + ", ".join(uncovered_tools)
        )
    if ghost_declarations:
        errors.append(
            "AUTO_APPROVED_BUILTIN_TOOLS declaration(s) for non-built-in tool(s): "
            + ", ".join(ghost_declarations)
        )
    if invalid_reasons:
        errors.append(
            "AUTO_APPROVED_BUILTIN_TOOLS reason(s) not in AUTO_APPROVE_REASONS: "
            + ", ".join(invalid_reasons)
        )

    ruleset_permissions = {rule.permission for rule in DEFAULT_RULESET}
    for perm in sorted(set(TOOL_PERMISSION_MAP.values()) - ruleset_permissions):
        reason = RULESET_COVERAGE_WHITELIST.get(perm)
        if reason is None:
            errors.append(
                f"Permission type {perm!r} has no DEFAULT_RULESET rule and no "
                "RULESET_COVERAGE_WHITELIST declaration (governance fail-closed)."
            )
        elif reason not in AUTO_APPROVE_REASONS:
            errors.append(
                f"RULESET_COVERAGE_WHITELIST reason for {perm!r} not in "
                "AUTO_APPROVE_REASONS."
            )

    missing_safety = sorted(BUILTIN_TOOL_NAMES - TOOL_SAFETY_METADATA.keys())
    if missing_safety:
        errors.append(
            "Built-in tool(s) missing TOOL_SAFETY_METADATA (fail-closed defaults): "
            + ", ".join(missing_safety)
        )

    missing_canonical = sorted(
        tool
        for tool in _CANONICAL_REQUIRED_TOOLS
        if tool not in TOOL_CANONICAL_PARAMS
    )
    if missing_canonical:
        errors.append(
            "Management/delegation/scheduling tool(s) missing TOOL_CANONICAL_PARAMS "
            "(allow-always matching falls back to full-arg hashing): "
            + ", ".join(missing_canonical)
        )

    coverage_matrix: dict[str, object] = {
        "builtin_tools": sorted(BUILTIN_TOOL_NAMES),
        "tool_coverage": {
            tool: {
                "permission": TOOL_PERMISSION_MAP.get(tool),
                "dynamic_resolved": tool in _DYNAMICALLY_RESOLVED_TOOLS,
                "auto_approved_reason": AUTO_APPROVED_BUILTIN_TOOLS.get(tool),
                "safety_declared": tool in TOOL_SAFETY_METADATA,
                "canonical_params": TOOL_CANONICAL_PARAMS.get(tool, []),
            }
            for tool in sorted(BUILTIN_TOOL_NAMES)
        },
        "permission_type_coverage": {
            perm: {
                "has_ruleset_rule": perm in ruleset_permissions,
                "whitelist_reason": RULESET_COVERAGE_WHITELIST.get(perm),
            }
            for perm in sorted(set(TOOL_PERMISSION_MAP.values()))
        },
    }
    return errors, coverage_matrix


def _check_default_enabled_product_parity() -> list[str]:
    """Ensure harness DEFAULT_ENABLED_PRODUCT_IDS matches server SSOT."""
    errors: list[str] = []
    server_path = str(SERVER_ROOT)
    if server_path not in sys.path:
        sys.path.insert(0, server_path)
    try:
        from app.services.agent.builtin_specs.builtin_tool_ids import (
            DEFAULT_ENABLED_BUILTIN_TOOLS,
        )

        from myrm_agent_harness.agent.tool_management.tool_catalog import (
            DEFAULT_ENABLED_PRODUCT_IDS,
        )
    except ImportError as exc:
        errors.append(f"Could not import server DEFAULT_ENABLED_BUILTIN_TOOLS: {exc}")
        return errors

    server_ids = frozenset(DEFAULT_ENABLED_BUILTIN_TOOLS)
    if server_ids != DEFAULT_ENABLED_PRODUCT_IDS:
        errors.append(
            "DEFAULT_ENABLED_PRODUCT_IDS drift: harness="
            f"{sorted(DEFAULT_ENABLED_PRODUCT_IDS)} server={sorted(server_ids)}; "
            "sync tool_catalog.py DEFAULT_ENABLED_PRODUCT_IDS with builtin_tool_ids.py"
        )
    return errors


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
        f"Layer breakdown (registered): CORE={layer_counts['CORE']} COMMON={layer_counts['COMMON']} "
        f"EXTENDED={layer_counts['EXTENDED']} EXTERNAL={layer_counts['EXTERNAL']}",
        "",
    ]

    missing = report.missing_registrations()
    duplicates = report.duplicate_declarations()
    ghosts: set[str] = set() if incremental else report.ghost_registrations()
    orphans: set[str] = set() if incremental else report.orphan_factories()
    meta_ghosts: set[str] = set() if incremental else (metadata_ghosts or set())

    if (
        not missing
        and not ghosts
        and not orphans
        and not duplicates
        and not meta_ghosts
    ):
        lines.append("PASS - tool registry consistent")
        return "\n".join(lines)

    if missing:
        lines.append(
            f"FAIL - {len(missing)} tool(s) defined but NOT registered in _TOOL_LAYERS:"
        )
        for name in sorted(missing):
            owners = [d for d in report.declarations if d.name == name]
            owner = owners[0]
            lines.append(
                f"  - {name}  ({owner.kind} @ {owner.file.relative_to(_repo_root)}:{owner.line})"
            )
        lines.append(
            "  Fix: register via `register_tool_layer()` in either tool_layers.py (harness)"
        )
        lines.append("       or _tool_layer_bootstrap.py (server).")
        lines.append("")

    if ghosts:
        lines.append(
            f"FAIL - {len(ghosts)} tool(s) registered but NO source defines them:"
        )
        for name in sorted(ghosts):
            lines.append(f"  - {name}")
        lines.append("  Fix: remove the dead registration entry.")
        lines.append("")

    if orphans:
        lines.append(
            f"FAIL - {len(orphans)} tool factory function(s) without any call site:"
        )
        for factory in sorted(orphans):
            origin = report.factories[factory]
            lines.append(f"  - {factory}  (defined @ {origin.relative_to(_repo_root)})")
        lines.append(
            "  Fix: either wire the factory into a startup path, or delete the dead code."
        )
        lines.append(
            "       To intentionally allow an unused factory, add it to ORPHAN_FACTORY_WHITELIST."
        )
        lines.append("")

    if meta_ghosts:
        lines.append(
            f"FAIL - {len(meta_ghosts)} registry metadata key(s) with NO @tool source:"
        )
        for name in sorted(meta_ghosts):
            lines.append(f"  - {name}")
        lines.append(
            "  Fix: remove dead keys from tool_registry.py maps or register the tool."
        )
        lines.append("")

    if duplicates:
        lines.append(
            f"FAIL - {len(duplicates)} tool name(s) declared in multiple source files:"
        )
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
        "EXTERNAL": counts.get("EXTERNAL", 0),
    }


def _build_doc_block(report: ScanReport) -> str:
    counts = _layer_counts(report)
    action_total = sum(counts.values())
    from myrm_agent_harness.agent.orchestration.hooks import RUNTIME_HOOK_NAMES
    from myrm_agent_harness.agent.orchestration.signals.catalog import (
        ORCHESTRATION_SIGNAL_NAMES,
    )
    from scripts.tool_registry_config import PTC_RUNTIME_TOOL_NAMES

    ptc_names = ", ".join(f"`{n}`" for n in sorted(PTC_RUNTIME_TOOL_NAMES))
    harness_total = counts["CORE"] + counts["COMMON"] + counts["EXTENDED"]
    return (
        f"{_BLOCK_BEGIN}\n"
        f"LLM tools: **{action_total}** "
        f"(Harness {harness_total}: CORE {counts['CORE']} + COMMON {counts['COMMON']} + "
        f"EXTENDED {counts['EXTENDED']}; External {counts['EXTERNAL']}: server vendor). "
        f"Orchestration signals: **{len(ORCHESTRATION_SIGNAL_NAMES)}**. "
        f"Runtime hooks: **{len(RUNTIME_HOOK_NAMES)}**. "
        f"PTC runtime tools: **{len(PTC_RUNTIME_TOOL_NAMES)}** ({ptc_names}). "
        "LLM-tool SSOT: `tool_layers.py` + `_tool_layer_bootstrap.py`. "
        "PTC SSOT: `agent/dynamic_workflow/tools.py` + `PTC_RUNTIME_TOOL_NAMES`. "
        "Orchestration SSOT: `agent/orchestration/`. "
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
        "Orchestration signals, runtime hooks, and PTC runtime tools "
        "(`spawn_subagent`, `notify`) are documented in §内部分类 above.\n\n"
        f"{table}\n"
        f"{_CATALOG_END}"
    )


def _update_doc_blocks(
    doc_path: Path, blocks: dict[str, str]
) -> tuple[bool, str | None]:
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
    parser.add_argument(
        "--incremental", action="store_true", help="Only consider files changed in git"
    )
    parser.add_argument(
        "--generate-docs", action="store_true", help="Refresh TOOL_COUNT blocks in docs"
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
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
        changed, err = _update_doc_blocks(
            _CATALOG_DOC_TARGET, {"catalog": catalog_block}
        )
        if changed:
            modified.append(_CATALOG_DOC_TARGET)
        if err:
            doc_errors.append(err)
        if doc_errors:
            print("ERROR: --generate-docs cannot update docs:", file=sys.stderr)
            for err in doc_errors:
                print(f"  - {err}", file=sys.stderr)
            print(
                "Add `<!-- TOOL_COUNT_BEGIN -->...<!-- TOOL_COUNT_END -->` markers.",
                file=sys.stderr,
            )
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
    catalog_invoke_violations = (
        [] if args.incremental else _scan_forbidden_catalog_invoke_terms()
    )
    from myrm_agent_harness.agent.tool_management.tool_catalog import (
        validate_tool_catalog,
    )

    # Layer-product gate is cheap (static _TOOL_LAYERS dict) — run in all modes so
    # pre-commit --incremental (.pre-commit-config.yaml) catches layer mistakes too.
    catalog_errors = validate_tool_catalog(load_registered_layers())
    # Governance coverage is a static metadata comparison — run in all modes so
    # pre-commit catches new tools that would silently bypass governance.
    governance_errors, coverage_matrix = _check_governance_coverage()
    parity_errors: list[str] = []
    if not args.incremental:
        parity_errors = _check_default_enabled_product_parity()
    fail = bool(
        missing
        or ghosts
        or orphans
        or duplicates
        or metadata_ghosts
        or bindmode_violations
        or catalog_invoke_violations
        or catalog_errors
        or parity_errors
        or governance_errors
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
                name: [
                    f"{decl.file.relative_to(_repo_root)}:{decl.line}" for decl in decls
                ]
                for name, decls in duplicates.items()
            },
            "governance_errors": governance_errors,
            "governance_coverage": coverage_matrix,
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
            print(
                f"FAIL - {len(bindmode_violations)} forbidden ToolBindMode legacy term(s):"
            )
            for path, line_no, line in bindmode_violations:
                try:
                    display = path.relative_to(_repo_root)
                except ValueError:
                    display = path
                print(f"  - {display}:{line_no}: {line}")
            print(
                "  Fix: use Turn1 registration + get_runtime_tools() for RUNTIME_ONLY hooks."
            )
        if catalog_invoke_violations:
            print(
                f"FAIL - {len(catalog_invoke_violations)} forbidden catalog_invoke legacy term(s):"
            )
            for path, line_no, line in catalog_invoke_violations:
                try:
                    display = path.relative_to(_repo_root)
                except ValueError:
                    display = path
                print(f"  - {display}:{line_no}: {line}")
            print(
                "  Fix: MCP overflow must use Direct FC or MCP PTC only; "
                "see FRAMEWORK_DESIGN_PRINCIPLES.md §7."
            )
        if catalog_errors:
            print(f"FAIL - {len(catalog_errors)} tool catalog metadata issue(s):")
            for err in catalog_errors:
                print(f"  - {err}")
            print("  Fix: update tool_catalog.py role/load overrides.")
        if parity_errors:
            print(
                f"FAIL - {len(parity_errors)} default-enabled product ID parity issue(s):"
            )
            for err in parity_errors:
                print(f"  - {err}")
        if governance_errors:
            print(
                f"FAIL - {len(governance_errors)} governance coverage issue(s):"
            )
            for err in governance_errors:
                print(f"  - {err}")
            print(
                "  Fix: register the tool in TOOL_PERMISSION_MAP, add a dynamic "
                "resolver branch, or declare it in AUTO_APPROVED_BUILTIN_TOOLS / "
                "RULESET_COVERAGE_WHITELIST with a valid AUTO_APPROVE_REASONS value."
            )

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

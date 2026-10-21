#!/usr/bin/env python3
"""CLI entry point for architecture boundary enforcement.

Validates framework-business separation by scanning Python imports.
Supports incremental mode for fast pre-commit checks.

Usage:
    python scripts/boundary_check.py                    # Full scan
    python scripts/boundary_check.py --incremental      # Only changed files (for pre-commit)
    python scripts/boundary_check.py --fix              # Auto-fix violations

Exit codes:
    0: No violations found
    1: Violations detected (or fixed with --fix)
    2: Internal error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.boundary_engine import (  # noqa: E402
    check_file,
    classify_priority,
    collect_imports,
    fix_violations,
    get_changed_harness_files,
    is_allowed_path,
    is_banned_import,
)

__all__ = [
    "_build_summary",
    "check_file",
    "classify_priority",
    "collect_imports",
    "fix_violations",
    "get_changed_harness_files",
    "is_allowed_path",
    "is_banned_import",
]


def _build_summary(
    all_messages: list[str],
    files_checked: int,
    total_violations: int,
) -> str:
    """Build a summary report with priority breakdown and statistics."""
    high = sum(1 for m in all_messages if "[HIGH]" in m)
    medium = sum(1 for m in all_messages if "[MEDIUM]" in m)
    low = sum(1 for m in all_messages if "[LOW]" in m)

    lines = [
        "",
        "=" * 80,
        "❌ BOUNDARY VIOLATIONS DETECTED",
        "=" * 80,
    ]

    if high:
        lines.append(f"\n🔴 HIGH Priority: {high} violation(s)")
        lines.extend(m for m in all_messages if "[HIGH]" in m)

    if medium:
        lines.append(f"\n🟡 MEDIUM Priority: {medium} violation(s)")
        lines.extend(m for m in all_messages if "[MEDIUM]" in m)

    if low:
        lines.append(f"\n🟢 LOW Priority: {low} violation(s)")
        lines.extend(m for m in all_messages if "[LOW]" in m)

    lines.extend(
        [
            "",
            "=" * 80,
            f"📊 Summary: {total_violations} violation(s) in {files_checked} files checked",
            f"   🔴 HIGH: {high}  🟡 MEDIUM: {medium}  🟢 LOW: {low}",
            "",
            "💡 Quick fix: python scripts/boundary_check.py --fix",
            "📖 Architecture guide: myrm-agent-harness/ARCHITECTURE.md",
            "=" * 80,
        ]
    )

    return "\n".join(lines)


def main() -> int:
    """Run boundary checking with optional auto-fix and incremental mode.

    Returns:
        Exit code (0 = success, 1 = violations found/fixed, 2 = error)
    """
    parser = argparse.ArgumentParser(description="Check framework-business boundaries")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically comment out violations",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only check files changed in git (for pre-commit hooks)",
    )
    args = parser.parse_args()

    try:
        harness_root = Path(__file__).parent.parent / "src" / "myrm_agent_harness"

        if not harness_root.exists():
            print(f"Error: Harness root not found: {harness_root}", file=sys.stderr)
            return 2

        if args.incremental:
            changed_files = get_changed_harness_files(harness_root)
            if changed_files is not None:
                py_files = sorted(changed_files)
                if not py_files:
                    print("✅ No harness files changed — boundary check skipped")
                    return 0
            else:
                py_files = sorted(harness_root.rglob("*.py"))
        else:
            py_files = sorted(harness_root.rglob("*.py"))

        total_violations = 0
        all_messages: list[str] = []
        files_checked = 0

        for py_file in py_files:
            files_checked += 1
            count, messages = check_file(py_file, harness_root, fix=args.fix)
            if count > 0:
                total_violations += count
                all_messages.extend(messages)

        if total_violations > 0:
            if args.fix:
                print(f"\n✅ Fixed {total_violations} violation(s)")
                print("\n📋 Modified files:")
                print("\n".join(all_messages))
                print("\n⚠️  Note: Violations are commented out. Please review and address.")
                print("📖 See: myrm-agent-harness/ARCHITECTURE.md")
                return 1

            report = _build_summary(all_messages, files_checked, total_violations)
            print(report, file=sys.stderr)
            return 1

        mode = "incremental" if args.incremental else "full"
        print(f"\n✅ Boundary check passed: No violations found ({files_checked} files, {mode} scan)")
        return 0

    except Exception as e:
        print(f"Internal error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

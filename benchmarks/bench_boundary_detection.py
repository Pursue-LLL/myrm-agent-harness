"""Performance benchmark for boundary detection.

Measures AST scan speed across the harness codebase to ensure
the detection mechanism does not introduce significant overhead.

Supports JSON output for CI regression detection:
    python benchmarks/bench_boundary_detection.py --json > result.json
    python benchmarks/bench_boundary_detection.py --check-regression baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.boundary_engine import (
    collect_imports,
    is_allowed_path,
    is_banned_import,
)

HARNESS_ROOT = Path(__file__).parent.parent / "src" / "myrm_agent_harness"

FULL_SCAN_THRESHOLD_SEC = 5.0
MICRO_THRESHOLD_US = 2.0
REGRESSION_TOLERANCE = 0.30


def bench_full_scan() -> dict[str, float | int]:
    """Benchmark full harness codebase scan."""
    start = time.perf_counter()

    files_scanned = 0
    imports_checked = 0
    violations_found = 0

    for py_file in HARNESS_ROOT.rglob("*.py"):
        if is_allowed_path(py_file, HARNESS_ROOT):
            continue

        files_scanned += 1
        for _, module in collect_imports(py_file):
            imports_checked += 1
            if is_banned_import(module):
                violations_found += 1

    elapsed = time.perf_counter() - start

    return {
        "elapsed_sec": round(elapsed, 3),
        "files_scanned": files_scanned,
        "imports_checked": imports_checked,
        "violations_found": violations_found,
        "files_per_sec": round(files_scanned / elapsed, 1),
        "imports_per_sec": round(imports_checked / elapsed, 1),
    }


def bench_import_matching() -> dict[str, float]:
    """Benchmark import matching micro-performance."""
    test_modules = [
        "myrm_agent_server",
        "myrm_agent_server.database",
        "myrm_control_plane.docker",
        "app.platform",
        "myrm_agent_harness",
        "os",
        "sys",
    ]

    iterations = 100000
    start = time.perf_counter()

    for _ in range(iterations):
        for module in test_modules:
            is_banned_import(module)

    elapsed = time.perf_counter() - start
    operations = iterations * len(test_modules)

    return {
        "operations_per_sec": round(operations / elapsed),
        "avg_time_us": round((elapsed / operations) * 1e6, 2),
    }


def check_regression(baseline_path: Path, current: dict[str, dict[str, float | int]]) -> bool:
    """Compare current results against a baseline file.

    Returns True if no regression detected, False otherwise.
    """
    baseline_data: dict[str, Any] = json.loads(baseline_path.read_text())
    baseline_scan: float = baseline_data["full_scan"]["elapsed_sec"]
    baseline_micro: float = baseline_data["import_matching"]["avg_time_us"]

    current_scan: float = current["full_scan"]["elapsed_sec"]
    current_micro: float = current["import_matching"]["avg_time_us"]

    passed = True

    scan_ratio = current_scan / baseline_scan if baseline_scan > 0 else 1.0
    if scan_ratio > (1.0 + REGRESSION_TOLERANCE):
        print(
            f"❌ Full scan regression: {baseline_scan:.3f}s → {current_scan:.3f}s "
            f"(+{(scan_ratio - 1) * 100:.0f}%, threshold: +{REGRESSION_TOLERANCE * 100:.0f}%)"
        )
        passed = False
    else:
        print(f"✅ Full scan: {current_scan:.3f}s (baseline: {baseline_scan:.3f}s)")

    micro_ratio = current_micro / baseline_micro if baseline_micro > 0 else 1.0
    if micro_ratio > (1.0 + REGRESSION_TOLERANCE):
        print(
            f"❌ Micro-benchmark regression: {baseline_micro:.2f}μs → {current_micro:.2f}μs "
            f"(+{(micro_ratio - 1) * 100:.0f}%, threshold: +{REGRESSION_TOLERANCE * 100:.0f}%)"
        )
        passed = False
    else:
        print(f"✅ Micro-benchmark: {current_micro:.2f}μs (baseline: {baseline_micro:.2f}μs)")

    return passed


def main() -> int:
    """Run all benchmarks and display results."""
    parser = argparse.ArgumentParser(description="Boundary detection performance benchmark")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--check-regression",
        type=Path,
        metavar="BASELINE",
        help="Compare against baseline JSON file",
    )
    parser.add_argument(
        "--save-baseline",
        type=Path,
        metavar="OUTPUT",
        help="Save current results as baseline",
    )
    args = parser.parse_args()

    scan_metrics = bench_full_scan()
    micro_metrics = bench_import_matching()

    results = {
        "full_scan": scan_metrics,
        "import_matching": micro_metrics,
    }

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    if args.save_baseline:
        args.save_baseline.write_text(json.dumps(results, indent=2))
        print(f"✅ Baseline saved to {args.save_baseline}")
        return 0

    if args.check_regression:
        if not args.check_regression.exists():
            print(f"⚠️  Baseline not found: {args.check_regression}, skipping regression check")
            return 0
        passed = check_regression(args.check_regression, results)
        return 0 if passed else 1

    # Default: human-readable output
    print("=" * 60)
    print("Boundary Detection Performance Benchmark")
    print("=" * 60)

    print("\n📊 Full Codebase Scan")
    print("-" * 60)
    print(f"Files scanned:      {scan_metrics['files_scanned']}")
    print(f"Imports checked:    {scan_metrics['imports_checked']}")
    print(f"Violations found:   {scan_metrics['violations_found']}")
    print(f"Elapsed time:       {scan_metrics['elapsed_sec']:.3f} sec")
    print(f"Throughput:         {scan_metrics['files_per_sec']:.1f} files/sec")
    print(f"                    {scan_metrics['imports_per_sec']:.1f} imports/sec")

    if scan_metrics["elapsed_sec"] >= FULL_SCAN_THRESHOLD_SEC:
        print(f"\n❌ FAIL: Full scan exceeds {FULL_SCAN_THRESHOLD_SEC}s threshold")
    elif scan_metrics["elapsed_sec"] >= 1.0:
        print("\n⚠️  WARN: Full scan takes >= 1 second")

    print("\n🔬 Import Matching Micro-Benchmark")
    print("-" * 60)
    print(f"Operations/sec:     {micro_metrics['operations_per_sec']}")
    print(f"Avg time per check: {micro_metrics['avg_time_us']:.2f} μs")

    if micro_metrics["avg_time_us"] < MICRO_THRESHOLD_US:
        print(f"\n✅ PASS: Import matching is < {MICRO_THRESHOLD_US} μs per check")
    else:
        print(f"\n❌ FAIL: Import matching exceeds {MICRO_THRESHOLD_US} μs")

    print("\n" + "=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

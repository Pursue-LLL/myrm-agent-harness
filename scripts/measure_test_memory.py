#!/usr/bin/env python3
"""Measure peak RSS (MB) for pytest targets on macOS via /usr/bin/time -l."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure_peak_rss_mb(cmd: list[str], timeout_s: int = 600) -> tuple[int, int, str]:
    """Return (peak_mb, exit_code, tail_output)."""
    full_cmd = ["/usr/bin/time", "-l", *cmd]
    try:
        proc = subprocess.run(
            full_cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return -1, -9, "TIMEOUT"

    combined = (proc.stdout or "") + (proc.stderr or "")
    peak_mb = -1
    for line in combined.splitlines():
        if "maximum resident set size" in line:
            # bytes on macOS time -l
            m = re.search(r"(\d+)", line.split("maximum resident set size")[-1])
            if m:
                peak_mb = int(int(m.group(1)) / (1024 * 1024))
            break
    return peak_mb, proc.returncode, combined[-1500:]


def main() -> int:
    targets: list[tuple[str, list[str]]] = [
        ("memory", ["uv", "run", "pytest", "-n0", "-q", "--tb=no", "tests/toolkits/memory", "-m", "not integration"]),
        ("browser_no_e2e", ["uv", "run", "pytest", "-n0", "-q", "--tb=no", "tests/toolkits/browser", "-m", "not integration and not e2e"]),
        ("agent_security", ["uv", "run", "pytest", "-n0", "-q", "--tb=no", "tests/agent/security"]),
        ("agent_meta_tools", ["uv", "run", "pytest", "-n0", "-q", "--tb=no", "tests/agent/meta_tools"]),
        ("context_mgmt", ["uv", "run", "pytest", "-n0", "-q", "--tb=no", "tests/agent/context_management"]),
        ("runtime", ["uv", "run", "pytest", "-n0", "-q", "--tb=no", "tests/runtime"]),
        ("backends", ["uv", "run", "pytest", "-n0", "-q", "--tb=no", "tests/backends"]),
        ("full_n0", ["uv", "run", "pytest", "-n0", "-q", "--tb=no", "tests", "-m", "not integration and not e2e and not performance", "--ignore=tests/agent/skills/curator/test_engine.py"]),
        ("full_nauto", ["uv", "run", "pytest", "-q", "--tb=no", "tests", "-m", "not integration and not e2e and not performance", "--ignore=tests/agent/skills/curator/test_engine.py"]),
    ]

    if len(sys.argv) > 1:
        names = set(sys.argv[1:])
        targets = [t for t in targets if t[0] in names]

    print(f"{'target':22s} {'exit':>5s} {'peak_mb':>8s}")
    print("-" * 40)
    for name, cmd in targets:
        peak, code, _ = measure_peak_rss_mb(cmd)
        peak_display = f"{peak:8d}" if peak >= 0 else "     N/A"
        print(f"{name:22s} {code:5d} {peak_display}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

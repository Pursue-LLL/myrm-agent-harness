"""Build-time platform key detection (no installed myrm_agent_harness required).

Keep logic aligned with ``myrm_agent_harness._runtime_platform`` (runtime wheel SSOT).
"""

from __future__ import annotations

import platform
import sys


def _is_musl_linux() -> bool:
    if sys.platform != "linux":
        return False
    report_getter = getattr(getattr(sys, "report", None), "getReport", None)
    if report_getter is None:
        return False
    report = report_getter()
    header = report.get("header") if isinstance(report, dict) else None
    if not isinstance(header, dict):
        return False
    return header.get("glibcVersionRuntime") is None


def _normalize_machine(raw: str) -> str:
    machine = raw.lower()
    if machine in {"amd64", "x86_64"}:
        return "x64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    return machine


def get_runtime_platform_key() -> str:
    """Return the platform key for the current machine."""
    machine = _normalize_machine(platform.machine())
    if sys.platform == "darwin":
        return f"darwin-{machine}"
    if sys.platform == "linux":
        libc = "-musl" if _is_musl_linux() else ""
        return f"linux-{machine}{libc}"
    if sys.platform == "win32":
        return f"win32-{machine}"
    msg = f"Unsupported platform for compiled core wheels: {sys.platform} {platform.machine()}"
    raise RuntimeError(msg)

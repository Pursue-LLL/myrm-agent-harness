"""Platform tag detection for per-platform core wheel builds.

Mirrors Claude Code's ``@anthropic-ai/claude-code-{platform}`` optional
dependency pattern adapted for Python / PEP 425 platform tags.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlatformSpec:
    """Normalized platform identifier for core wheel naming."""

    key: str
    package_suffix: str
    nuitka_target: str | None


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


def get_current_platform() -> PlatformSpec:
    """Detect the current platform for core wheel selection."""
    machine = _normalize_machine(platform.machine())
    if sys.platform == "darwin":
        key = f"darwin-{machine}"
        return PlatformSpec(key=key, package_suffix=key, nuitka_target=f"macos-{machine}")
    if sys.platform == "linux":
        libc = "musl" if _is_musl_linux() else ""
        key = f"linux-{machine}{'-musl' if libc else ''}"
        nuitka = f"linux-{machine}"
        if libc:
            nuitka = f"{nuitka}-musl"
        return PlatformSpec(key=key, package_suffix=key, nuitka_target=nuitka)
    if sys.platform == "win32":
        key = f"win32-{machine}"
        return PlatformSpec(key=key, package_suffix=key, nuitka_target=f"windows-{machine}-msvc")
    msg = f"Unsupported platform for compiled core wheels: {sys.platform} {platform.machine()}"
    raise RuntimeError(msg)


def core_package_name(platform_key: str | None = None) -> str:
    """Return the PyPI distribution name for a platform core package."""
    key = platform_key or get_current_platform().key
    return f"myrm-agent-harness-core-{key}"


ALL_PLATFORMS: tuple[str, ...] = (
    "darwin-arm64",
    "darwin-x64",
    "linux-x64",
    "linux-arm64",
    "win32-x64",
    "win32-arm64",
)

# rc1 PyPI publish scope: Mac dev + Linux x64 Docker/CI. Expand to ALL_PLATFORMS before GA.
PUBLISH_PLATFORMS: tuple[str, ...] = (
    "darwin-arm64",
    "linux-x64",
)

SUPPORTED_PLATFORMS = ALL_PLATFORMS

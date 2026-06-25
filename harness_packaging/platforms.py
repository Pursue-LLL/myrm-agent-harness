"""Platform tag detection for per-platform core wheel builds.

Mirrors Claude Code's ``@anthropic-ai/claude-code-{platform}`` optional
dependency pattern adapted for Python / PEP 425 platform tags.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlatformSpec:
    """Normalized platform identifier for core wheel naming."""

    key: str
    package_suffix: str
    nuitka_target: str | None
    pep508_marker: str
    is_musl: bool = False


def get_current_platform() -> PlatformSpec:
    """Detect the current platform for core wheel selection."""
    from harness_packaging.runtime_platform import get_runtime_platform_key

    return platform_spec_for_key(get_runtime_platform_key())


def platform_spec_for_key(key: str) -> PlatformSpec:
    """Resolve a CI matrix platform key to a Nuitka build spec."""
    if key not in ALL_PLATFORMS:
        msg = f"Unknown platform key: {key!r}. Expected one of {ALL_PLATFORMS}"
        raise ValueError(msg)
    os_name, remainder = key.split("-", 1)
    is_musl = remainder.endswith("-musl")
    machine = remainder.removesuffix("-musl")
    if os_name == "darwin":
        marker = (
            "platform_system == 'Darwin' and platform_machine == 'arm64'"
            if machine == "arm64"
            else "platform_system == 'Darwin' and platform_machine == 'x86_64'"
        )
        return PlatformSpec(key=key, package_suffix=key, nuitka_target=f"macos-{machine}", pep508_marker=marker)
    if os_name == "linux":
        nuitka = f"linux-{machine}{'-musl' if is_musl else ''}"
        marker = (
            "platform_system == 'Linux' and platform_machine == 'x86_64'"
            if machine == "x64"
            else "platform_system == 'Linux' and platform_machine == 'aarch64'"
        )
        return PlatformSpec(
            key=key,
            package_suffix=key,
            nuitka_target=nuitka,
            pep508_marker=marker,
            is_musl=is_musl,
        )
    if os_name == "win32":
        marker = (
            "platform_system == 'Windows' and platform_machine == 'AMD64'"
            if machine == "x64"
            else "platform_system == 'Windows' and platform_machine == 'ARM64'"
        )
        return PlatformSpec(key=key, package_suffix=key, nuitka_target=f"windows-{machine}-msvc", pep508_marker=marker)
    msg = f"Unsupported platform key: {key!r}"
    raise ValueError(msg)


def core_package_name(platform_key: str | None = None) -> str:
    """Return the PyPI distribution name for a platform core package."""
    key = platform_key or get_current_platform().key
    return f"myrm-agent-harness-core-{key}"


ALL_PLATFORMS: tuple[str, ...] = (
    "darwin-arm64",
    "darwin-x64",
    "linux-x64",
    "linux-arm64",
    "linux-x64-musl",
    "linux-arm64-musl",
    "win32-x64",
    "win32-arm64",
)

PUBLISH_PLATFORMS: tuple[str, ...] = ALL_PLATFORMS

SUPPORTED_PLATFORMS = ALL_PLATFORMS

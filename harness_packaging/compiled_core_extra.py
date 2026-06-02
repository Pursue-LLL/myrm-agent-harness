"""Generate compiled-core optional-dependencies for release wheel metadata."""

from __future__ import annotations

from harness_packaging.platforms import SUPPORTED_PLATFORMS


def compiled_core_dependency_lines(version: str) -> list[str]:
    """Return PEP 508 lines for the compiled-core extra (one platform package each)."""
    marker_by_platform: dict[str, str] = {
        "darwin-arm64": "platform_system == 'Darwin' and platform_machine == 'arm64'",
        "darwin-x64": "platform_system == 'Darwin' and platform_machine == 'x86_64'",
        "linux-x64": "platform_system == 'Linux' and platform_machine == 'x86_64'",
        "linux-arm64": "platform_system == 'Linux' and platform_machine == 'aarch64'",
        "win32-x64": "platform_system == 'Windows' and platform_machine == 'AMD64'",
        "win32-arm64": "platform_system == 'Windows' and platform_machine == 'ARM64'",
    }
    lines: list[str] = []
    for platform_key in SUPPORTED_PLATFORMS:
        marker = marker_by_platform[platform_key]
        package = f"myrm-agent-harness-core-{platform_key}"
        lines.append(f'  "{package}=={version}; {marker}",')
    return lines


def inject_compiled_core_extra(pyproject_text: str, version: str) -> str:
    """Insert compiled-core optional-dependencies before [tool.uv] if missing."""
    if "compiled-core = [" in pyproject_text:
        return pyproject_text

    block_lines = [
        "# Injected at release wheel build; platform packages must exist on PyPI.",
        "compiled-core = [",
        *compiled_core_dependency_lines(version),
        "]",
        "",
    ]
    needle = "\n[tool.uv]"
    if needle not in pyproject_text:
        msg = "Could not locate [tool.uv] section for compiled-core injection"
        raise ValueError(msg)
    return pyproject_text.replace(needle, "\n" + "\n".join(block_lines) + needle, 1)

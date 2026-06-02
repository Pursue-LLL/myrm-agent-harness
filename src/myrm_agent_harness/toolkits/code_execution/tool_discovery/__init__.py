"""CLI Tool Discovery — detect available CLI tools and build agent prompt context.

[INPUT]
.detector::detect_all (POS: CLI tool detection engine)
.detector::refresh_cache (POS: CLI tool detection engine)
.detector::get_install_hint (POS: CLI tool detection engine)
.types::DetectedTool (POS: CLI tool discovery data types)
.types::ToolDefinition (POS: CLI tool discovery data types)

[OUTPUT]
get_cli_tools_context: build installed CLI tools list injectable into System Prompt (~165 tokens)
detect_all: re-export from detector
refresh_cache: re-export from detector
get_install_hint: re-export from detector
DetectedTool: re-export from types
ToolDefinition: re-export from types

[POS]
CLI tool auto-discovery module entry point. Provides get_cli_tools_context() one-stop API to detect
host CLI tools and format them as a prompt fragment. Provides get_install_hint() for error message
system to query platform-specific install commands.
"""

from __future__ import annotations

from .detector import detect_all, get_install_hint, refresh_cache
from .types import DetectedTool, ToolDefinition


def get_cli_tools_context(*, lang: str = "en") -> str | None:
    """Build a compact prompt section listing available CLI tools.

    Returns None if no tools are detected (caller should skip injection).
    Result is stable across calls (process-level cache) and suitable for
    System Prompt — will not break Prompt Cache.

    Args:
        lang: "en" or "zh" — selects which description to include.
    """
    tools = detect_all()
    if not tools:
        return None

    use_zh = lang.startswith("zh")
    lines: list[str] = []
    for t in tools:
        desc = t.desc_zh if use_zh else t.desc_en
        label = f"{t.bin_name} ({t.id})" if t.bin_name != t.id else t.id
        lines.append(f"{label}: {desc}")

    return "\n<cli_tools>\n" + "\n".join(lines) + "\n</cli_tools>"


__all__ = [
    "DetectedTool",
    "ToolDefinition",
    "detect_all",
    "get_cli_tools_context",
    "get_install_hint",
    "refresh_cache",
]

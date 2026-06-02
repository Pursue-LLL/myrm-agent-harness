"""CLI tool detector.

[INPUT]
.catalog::TOOL_CATALOG (POS: CLI tool catalog data layer)
.types::DetectedTool (POS: CLI tool discovery data types)
.types::ToolDefinition (POS: CLI tool discovery data types)

[OUTPUT]
detect_all: detect all installed CLI tools on the host, returns list[DetectedTool]
refresh_cache: force rescan and update process-level cache
get_install_hint: look up platform-specific install command by bin_name

[POS]
CLI tool detection engine. Scans tools in TOOL_CATALOG using shutil.which(), process-level cached, <1ms.
Provides get_install_hint() for error message system to query install commands.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from .catalog import TOOL_CATALOG
from .types import DetectedTool, ToolDefinition

_BIN_TO_TOOL: dict[str, ToolDefinition] = {bn: tool for tool in TOOL_CATALOG for bn in tool.bin_names}


def _build_extra_dirs() -> tuple[str, ...]:
    """Build extra PATH directories, gracefully handling missing HOME."""
    dirs = ["/usr/local/bin", "/opt/homebrew/bin", "/opt/homebrew/sbin"]
    try:
        home = Path.home()
        dirs.append(str(home / ".local" / "bin"))
        dirs.append(str(home / ".cargo" / "bin"))
    except RuntimeError:
        pass
    return tuple(dirs)


_EXTRA_PATH_DIRS: tuple[str, ...] = _build_extra_dirs()

_cache: list[DetectedTool] | None = None


def _expanded_path() -> str:
    """Build an expanded PATH that includes common tool directories."""
    current = os.environ.get("PATH", os.defpath)
    existing = set(current.split(os.pathsep))
    extras = [d for d in _EXTRA_PATH_DIRS if d not in existing and os.path.isdir(d)]
    if not extras:
        return current
    return current + os.pathsep + os.pathsep.join(extras)


def _detect_one(tool: ToolDefinition, path: str) -> DetectedTool | None:
    """Check if any of the tool's binary names exist on the expanded PATH."""
    for bin_name in tool.bin_names:
        found = shutil.which(bin_name, path=path)
        if found:
            return DetectedTool(
                id=tool.id,
                bin_name=bin_name,
                bin_path=Path(found),
                desc_en=tool.desc_en,
                desc_zh=tool.desc_zh,
                tags=tool.tags,
            )
    return None


def detect_all(*, use_cache: bool = True) -> list[DetectedTool]:
    """Detect all cataloged tools present on the host.

    Uses process-level cache by default. Pass use_cache=False to force re-scan.
    Total time: <1ms for ~25 tools (shutil.which is a pure filesystem check).
    """
    global _cache
    if use_cache and _cache is not None:
        return _cache

    path = _expanded_path()
    results: list[DetectedTool] = []
    for tool in TOOL_CATALOG:
        detected = _detect_one(tool, path)
        if detected:
            results.append(detected)

    _cache = results
    return results


def refresh_cache() -> list[DetectedTool]:
    """Force re-scan and update the process-level cache."""
    global _cache
    _cache = None
    return detect_all(use_cache=False)


def get_install_hint(bin_name: str) -> str | None:
    """Look up a platform-specific install command for a CLI tool.

    Uses a pre-built reverse index (_BIN_TO_TOOL) for O(1) lookup.
    Returns None if the tool is not in the catalog or has no hint
    for the current platform.
    """
    tool = _BIN_TO_TOOL.get(bin_name)
    if not tool or not tool.install_hints:
        return None
    return tool.install_hints.get(platform.system())

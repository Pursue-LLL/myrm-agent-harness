"""Lightweight stat-based workspace file change detection.

Compares pre/post file snapshots (mtime + size) to generate a concise
human-readable diff summary for Verifier agents.

[INPUT]
- agent.sub_agents.workspace_isolation::_CLONE_IGNORE_DIRS (POS: Workspace isolation忽略目录集合)

[OUTPUT]
- take_workspace_snapshot: Collect {relative_path: (mtime, size)} mapping.
- diff_snapshots: Generate diff summary from two snapshots.

[POS]
Workspace diff for adversarial verification — stat-based, no git dependency.
"""

from __future__ import annotations

import os
from pathlib import Path

from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
    _CLONE_IGNORE_DIRS as _SNAPSHOT_IGNORE_DIRS,
)

_MAX_SNAPSHOT_FILES = 5000


def take_workspace_snapshot(workspace: str | Path) -> dict[str, tuple[float, int]]:
    """Collect {relative_path: (mtime, size)} for all tracked files."""
    root = Path(workspace)
    if not root.is_dir():
        return {}
    snapshot: dict[str, tuple[float, int]] = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SNAPSHOT_IGNORE_DIRS]
        for f in files:
            fp = Path(dirpath) / f
            rel = str(fp.relative_to(root))
            try:
                st = fp.stat()
                snapshot[rel] = (st.st_mtime, st.st_size)
            except OSError:
                pass
        if len(snapshot) > _MAX_SNAPSHOT_FILES:
            break
    return snapshot


def diff_snapshots(
    before: dict[str, tuple[float, int]],
    after: dict[str, tuple[float, int]],
) -> str:
    """Generate a concise human-readable diff summary between two snapshots.

    Returns empty string if no changes detected.
    """
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    modified = sorted(
        k for k in before.keys() & after.keys()
        if before[k] != after[k]
    )

    if not added and not removed and not modified:
        return ""

    lines: list[str] = ["## Workspace Changes (Worker Execution Diff)"]
    if added:
        lines.append(f"\n### Added ({len(added)} files)")
        for f in added[:30]:
            lines.append(f"- `{f}`")
        if len(added) > 30:
            lines.append(f"- ... and {len(added) - 30} more")
    if modified:
        lines.append(f"\n### Modified ({len(modified)} files)")
        for f in modified[:30]:
            size_before, size_after = before[f][1], after[f][1]
            delta = size_after - size_before
            sign = "+" if delta >= 0 else ""
            lines.append(f"- `{f}` ({sign}{delta} bytes)")
        if len(modified) > 30:
            lines.append(f"- ... and {len(modified) - 30} more")
    if removed:
        lines.append(f"\n### Removed ({len(removed)} files)")
        for f in removed[:20]:
            lines.append(f"- `{f}`")
        if len(removed) > 20:
            lines.append(f"- ... and {len(removed) - 20} more")

    return "\n".join(lines)

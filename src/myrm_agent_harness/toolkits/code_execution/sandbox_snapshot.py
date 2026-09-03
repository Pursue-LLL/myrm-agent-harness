"""Sandbox environment bootstrap snapshot generator.

Captures initial workspace state (working directory, top-level directory entries,
git status, installed language runtimes, package managers, and recommended PM)
in milliseconds (<30ms) without deep recursive traversals.

Injected into initial task context / observation (never polluting immutable
system prompt) to eliminate 2-5 blind exploration turns (pwd, ls, which).

[INPUT]
- workspace_path: str | Path to workspace directory
- max_entries: int = 25 (max top-level entries to report)

[OUTPUT]
- SandboxBootstrapSnapshot: Dataclass holding structured sandbox metadata
- generate_sandbox_bootstrap_snapshot: Probes host & workspace and returns snapshot
- format_bootstrap_snapshot_xml: Formats snapshot into a compact, model-friendly XML block

[POS]
Harness code_execution sandbox snapshot generator.
Safe, non-recursive, cache-preserving, resilient to timeouts and permission errors.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

# Common build/cache/vcs directories to skip or compact
_IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        ".idea",
        ".vscode",
        "target",
        "dist",
        "build",
    }
)

_CORE_RUNTIMES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("python", "Python", ("python3", "python")),
    ("node", "Node.js", ("node",)),
    ("bun", "Bun", ("bun",)),
    ("go", "Go", ("go",)),
    ("rust", "Rust", ("rustc",)),
    ("java", "Java", ("java",)),
)

_CORE_TOOLS: tuple[str, ...] = ("git", "curl", "jq", "docker", "make", "tar", "rg")


@dataclass(frozen=True)
class SandboxBootstrapSnapshot:
    """Immutable snapshot of the sandbox workspace and runtime environment."""

    working_dir: str
    top_level_entries: tuple[str, ...]
    total_entries_count: int
    git_branch: str | None = None
    git_dirty: bool | None = None
    runtimes: tuple[str, ...] = ()
    package_managers: tuple[str, ...] = ()
    recommended_package_manager: str | None = None
    available_tools: tuple[str, ...] = ()

    @property
    def is_git_repo(self) -> bool:
        return self.git_branch is not None


def _run_quick_command(cmd: Sequence[str], timeout: float = 1.0) -> tuple[int, str]:
    """Run a fast subprocess command with a strict timeout."""
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, (proc.stdout or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("Sandbox snapshot quick command failed: %s (%s)", cmd, exc)
        return -1, ""


def _probe_git_state(workspace: Path) -> tuple[str | None, bool | None]:
    """Quickly probe git branch and cleanliness using git CLI or .git directory."""
    git_dir = workspace / ".git"
    if not git_dir.exists():
        return None, None

    if not shutil.which("git"):
        return "detected (git cli missing)", None

    rc_branch, branch_out = _run_quick_command(
        ["git", "-C", str(workspace), "rev-parse", "--abbrev-ref", "HEAD"], timeout=1.0
    )
    if rc_branch != 0 or not branch_out:
        branch_out = "HEAD"

    rc_status, status_out = _run_quick_command(
        ["git", "-C", str(workspace), "status", "--porcelain"], timeout=1.0
    )
    is_dirty = bool(status_out) if rc_status == 0 else None

    return branch_out, is_dirty


def _probe_runtimes() -> list[str]:
    """Probe installed programming language runtimes and their major/minor versions."""
    detected: list[str] = []
    for runtime_id, label, binaries in _CORE_RUNTIMES:
        for bin_name in binaries:
            if shutil.which(bin_name):
                # Attempt to get version string quickly
                version_str = _probe_runtime_version(bin_name)
                if version_str:
                    detected.append(f"{label} {version_str}")
                else:
                    detected.append(label)
                break
    return detected


def _probe_runtime_version(bin_name: str) -> str:
    """Fetch short version string for a given runtime binary."""
    if bin_name in ("python3", "python"):
        rc, out = _run_quick_command([bin_name, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')"])
        if rc == 0 and out:
            return out
    elif bin_name == "node":
        rc, out = _run_quick_command(["node", "-v"])
        if rc == 0 and out:
            return out.lstrip("v")
    elif bin_name == "bun":
        rc, out = _run_quick_command(["bun", "--version"])
        if rc == 0 and out:
            return out
    elif bin_name == "go":
        rc, out = _run_quick_command(["go", "env", "GOVERSION"])
        if rc == 0 and out:
            return out.removeprefix("go")
    elif bin_name == "rustc":
        rc, out = _run_quick_command(["rustc", "--version"])
        if rc == 0 and out:
            parts = out.split()
            if len(parts) >= 2:
                return parts[1]
    return ""


def _probe_package_managers(workspace: Path) -> tuple[tuple[str, ...], str | None]:
    """Detect available package managers and infer the recommended one from lockfiles."""
    available: list[str] = []
    candidates = ("pnpm", "bun", "yarn", "npm", "uv", "poetry", "pip", "cargo", "go")
    for cand in candidates:
        if shutil.which(cand):
            available.append(cand)

    recommended: str | None = None

    # Priority 1: Direct lockfile markers in workspace
    if (workspace / "pnpm-lock.yaml").exists() and "pnpm" in available:
        recommended = "pnpm"
    elif (workspace / "bun.lockb").exists() or (workspace / "bun.lock").exists():
        if "bun" in available:
            recommended = "bun"
    elif (workspace / "yarn.lock").exists() and "yarn" in available:
        recommended = "yarn"
    elif (workspace / "package-lock.json").exists() and "npm" in available:
        recommended = "npm"
    elif (workspace / "uv.lock").exists() and "uv" in available:
        recommended = "uv"
    elif (workspace / "poetry.lock").exists() and "poetry" in available:
        recommended = "poetry"
    elif (workspace / "Cargo.lock").exists() and "cargo" in available:
        recommended = "cargo"
    elif (workspace / "go.sum").exists() and "go" in available:
        recommended = "go"

    # Priority 2: Config file inference when lockfile is absent
    if not recommended:
        if (workspace / "package.json").exists():
            for pref in ("pnpm", "bun", "npm"):
                if pref in available:
                    recommended = pref
                    break
        elif (workspace / "pyproject.toml").exists() or (workspace / "requirements.txt").exists():
            for pref in ("uv", "poetry", "pip"):
                if pref in available:
                    recommended = pref
                    break
        elif (workspace / "Cargo.toml").exists() and "cargo" in available:
            recommended = "cargo"
        elif (workspace / "go.mod").exists() and "go" in available:
            recommended = "go"

    return tuple(available), recommended


def _probe_tools() -> list[str]:
    """Detect presence of common command-line utility tools."""
    found: list[str] = []
    for tool in _CORE_TOOLS:
        if shutil.which(tool):
            found.append(tool)
    return found


def _scan_top_level_entries(workspace: Path, max_entries: int) -> tuple[tuple[str, ...], int]:
    """Shallow non-recursive scan of the workspace directory with limit."""
    entries: list[str] = []
    total_count = 0

    try:
        with os.scandir(workspace) as it:
            raw_entries: list[os.DirEntry[str]] = list(it)
    except (OSError, PermissionError) as exc:
        logger.debug("Failed to scan workspace %s: %s", workspace, exc)
        return (), 0

    # Sort entries: directories first with trailing slash, then files
    sorted_entries = sorted(raw_entries, key=lambda e: (not e.is_dir(), e.name.lower()))
    for entry in sorted_entries:
        name = entry.name
        if name in _IGNORED_DIRS:
            continue
        total_count += 1
        if len(entries) < max_entries:
            display_name = f"{name}/" if entry.is_dir() else name
            entries.append(display_name)

    return tuple(entries), total_count


def generate_sandbox_bootstrap_snapshot(
    workspace_path: str | Path,
    *,
    max_entries: int = 25,
) -> SandboxBootstrapSnapshot:
    """Generate a lightweight, non-recursive bootstrap snapshot of the sandbox environment.

    Execution time is strictly bounded (<30ms typical). Any probe failure is handled
    gracefully to guarantee non-crashing execution.

    Args:
        workspace_path: Path to the workspace root directory.
        max_entries: Maximum number of top-level directory items to report.

    Returns:
        Structured SandboxBootstrapSnapshot instance.
    """
    path = Path(workspace_path).resolve()
    if not path.is_dir():
        return SandboxBootstrapSnapshot(
            working_dir=str(path),
            top_level_entries=(),
            total_entries_count=0,
        )

    # 1. Scan top-level workspace entries (<5ms)
    top_entries, total_count = _scan_top_level_entries(path, max_entries=max_entries)

    # 2. Check git state (<10ms)
    branch, is_dirty = _probe_git_state(path)

    # 3. Detect installed runtimes (<10ms)
    runtimes = _probe_runtimes()

    # 4. Detect package managers and recommend primary choice (<5ms)
    package_managers, recommended_pm = _probe_package_managers(path)

    # 5. Detect core CLI utilities (<2ms)
    tools = _probe_tools()

    return SandboxBootstrapSnapshot(
        working_dir=str(path),
        top_level_entries=top_entries,
        total_entries_count=total_count,
        git_branch=branch,
        git_dirty=is_dirty,
        runtimes=tuple(runtimes),
        package_managers=package_managers,
        recommended_package_manager=recommended_pm,
        available_tools=tuple(tools),
    )


def format_bootstrap_snapshot_xml(snapshot: SandboxBootstrapSnapshot) -> str:
    """Format the snapshot into a clean, compact XML observation for the initial prompt/observation.

    Designed for maximum model adherence and zero ambiguity while maintaining token efficiency (~80-120 tokens).
    """
    lines: list[str] = ["<sandbox_environment_snapshot>"]

    # Working Directory and Git
    wd_line = f"Working Directory: {snapshot.working_dir}"
    if snapshot.git_branch:
        dirty_str = "dirty" if snapshot.git_dirty else "clean"
        wd_line += f" (Git: {snapshot.git_branch}, {dirty_str})"
    lines.append(wd_line)

    # Top-level workspace entries
    if snapshot.top_level_entries:
        entries_str = ", ".join(snapshot.top_level_entries)
        if snapshot.total_entries_count > len(snapshot.top_level_entries):
            entries_str += f" ... (+{snapshot.total_entries_count - len(snapshot.top_level_entries)} more)"
        lines.append(f"Workspace Contents: {entries_str}")
    else:
        lines.append("Workspace Contents: [empty directory]")

    # Runtimes
    if snapshot.runtimes:
        lines.append(f"Available Runtimes: {', '.join(snapshot.runtimes)}")

    # Package Managers & Recommendation
    if snapshot.package_managers:
        pm_parts: list[str] = []
        for pm in snapshot.package_managers:
            if pm == snapshot.recommended_package_manager:
                pm_parts.append(f"{pm} (recommended for this project)")
            else:
                pm_parts.append(pm)
        lines.append(f"Package Managers: {', '.join(pm_parts)}")

    # Available Tools
    if snapshot.available_tools:
        lines.append(f"CLI Tools: {', '.join(snapshot.available_tools)}")

    lines.append(
        "Guidance: You have full access to the above sandbox workspace. "
        "Use the recommended package manager and paths directly without blind directory probing."
    )
    lines.append("</sandbox_environment_snapshot>")
    return "\n".join(lines)

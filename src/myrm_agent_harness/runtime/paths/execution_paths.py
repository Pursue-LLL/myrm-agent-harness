"""Unified execution path constants and utilities.

Defines standard paths for execution environments with persistent volume support.
Physical isolation is provided by the deployment environment (e.g., containers,
separate processes), not by this module.

Path Structure:
    /persistent/                      ← Persistent storage mount point
    ├── .context/                     ← Context offload directory
    │   ├── {session_id}/            ← Per-session isolation
    │   │   ├── compacted/           ← Compressed tool outputs
    │   │   │   └── sha256/{prefix}/ ← Content-addressed compacted outputs
    │   │   ├── evicted/             ← Large bash output eviction files
    │   │   ├── snapshots/           ← Pre-compression full conversation snapshots
    │   │   └── scratchpad/          ← Agent active externalization
    │   └── system/                  ← System configuration files
    ├── .memories/                    ← Memory storage
    └── workspace/                    ← User workspace
        ├── projects/                ← User projects
        ├── artifacts/               ← Agent-generated artifacts
        └── skills/                  ← Custom skills

Compatibility:
    Supports both /persistent and /workspace paths for flexible deployment.

Persistent root:
    The volume root is ``/persistent`` unless the deployment layer sets ``MYRM_PERSISTENT_ROOT``
    (local development without a mount). Every root is derived from it on each call, so a root
    configured after import is honored by every caller and nothing keeps a stale copy.

[INPUT]
- MYRM_PERSISTENT_ROOT (optional infra env): persistent volume root; default /persistent

[OUTPUT]
- PERSISTENT_ROOT_ENV: Name of the environment variable that relocates the persistent volume root.
- get_persistent_root: The persistent volume root currently in effect.
- get_workspace_root: The workspace root under the persistent volume.
- get_context_root: The context root currently in effect.
- get_memories_root: The memory storage root under the persistent volume.
- get_evicted_output_path: Get path for evicted large bash output (auto-generates UU...
- get_scratchpad_path: Get path for agent scratchpad file.
- get_snapshot_path: Get path for pre-compression conversation snapshot (auto-...
- get_system_config_path: Get path for system configuration file.
- get_context_session_dir / get_context_subdir / get_context_file_path: Session-scoped context layout.
- get_workspace_relative_path: Convert an absolute path to a workspace-relative one.
- ensure_context_dir_exists: Create a session context directory.
- sanitize_path_segment / sanitize_filename: Traversal-safe path components.
- is_context_path: Whether a path lies under the context root.

[POS]
Unified execution path constants and utilities.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Literal

# ============ Core Path Roots ============

# Environment variable the deployment layer sets when the volume is not mounted at /persistent.
PERSISTENT_ROOT_ENV = "MYRM_PERSISTENT_ROOT"

_DEFAULT_PERSISTENT_ROOT = "/persistent"

# Alternative workspace path for compatibility
LEGACY_WORKSPACE_ROOT = "/workspace"


def get_persistent_root() -> str:
    """Return the persistent volume root currently in effect.

    Read from ``MYRM_PERSISTENT_ROOT`` at call time, falling back to ``/persistent``. Callers that
    need a root import this function instead of a constant, so they always agree with the paths
    the writers produce, whenever the deployment layer sets the variable.
    """
    configured = os.environ.get(PERSISTENT_ROOT_ENV, "").strip().rstrip("/")
    return configured or _DEFAULT_PERSISTENT_ROOT


def get_workspace_root() -> str:
    """Return the workspace root (user files, projects, artifacts)."""
    return f"{get_persistent_root()}/workspace"


def get_context_root() -> str:
    """Return the context offload root (compressed tool outputs, scratchpad)."""
    return f"{get_persistent_root()}/.context"


def get_memories_root() -> str:
    """Return the memory storage root."""
    return f"{get_persistent_root()}/.memories"


# ============ Context Subdirectories ============

ContextSubdir = Literal["compacted", "scratchpad", "snapshots", "evicted"]

CONTEXT_SUBDIRS: dict[ContextSubdir, str] = {
    "compacted": "compacted",  # Compressed tool outputs
    "scratchpad": "scratchpad",  # Agent active externalization
    "snapshots": "snapshots",  # Pre-compression full conversation snapshots
    "evicted": "evicted",  # Large tool/web output spill files (UECD)
}


# ============ Specialized Path Functions ============


def get_evicted_output_path(session_id: str, *, source: str = "output", ext: str = "txt") -> str:
    """Get path for evicted large output (auto-generates UUID basename).

    Args:
        session_id: Session identifier (e.g., chat_id)
        source: Filename prefix (output, web_fetch, mcp, tool, filter)
        ext: File extension (txt, md, log, json)

    Returns:
        Absolute path to evicted output file

    Examples:
        >>> get_evicted_output_path("chat_abc123")
        '/persistent/.context/chat_abc123/evicted/output_a3f5c8d1.txt'

    """
    from myrm_agent_harness.agent.context_management.infra.evicted import (
        build_evicted_basename,
    )

    safe_session = sanitize_path_segment(session_id)
    filename = build_evicted_basename(source, ext=ext)
    return f"{get_context_root()}/{safe_session}/evicted/{filename}"


def get_scratchpad_path(session_id: str, filename: str) -> str:
    """Get path for agent scratchpad file.

    Args:
        session_id: Session identifier
        filename: Scratchpad filename

    Returns:
        Absolute path to scratchpad file

    Examples:
        >>> get_scratchpad_path("chat_abc123", "notes.txt")
        '/persistent/.context/chat_abc123/scratchpad/notes.txt'

    """
    safe_session = sanitize_path_segment(session_id)
    safe_filename = sanitize_filename(filename)
    return f"{get_context_root()}/{safe_session}/scratchpad/{safe_filename}"


def get_snapshot_path(session_id: str, compressed: bool = False) -> str:
    """Get path for pre-compression conversation snapshot (auto-generates timestamped UUID).

    Args:
        session_id: Session identifier (e.g., chat_id)
        compressed: Whether the file will be gzip-compressed (affects extension)

    Returns:
        Absolute path to snapshot file

    Examples:
        >>> get_snapshot_path("chat_abc123")
        '/persistent/.context/chat_abc123/snapshots/1712345678_a3f5c8d1.jsonl'
        >>> get_snapshot_path("chat_abc123", compressed=True)
        '/persistent/.context/chat_abc123/snapshots/1712345678_a3f5c8d1.jsonl.gz'

    """
    safe_session = sanitize_path_segment(session_id)
    timestamp = int(time.time())
    unique_id = uuid.uuid4().hex[:8]
    ext = ".jsonl.gz" if compressed else ".jsonl"
    filename = f"{timestamp}_{unique_id}{ext}"
    return f"{get_context_root()}/{safe_session}/snapshots/{filename}"


def get_system_config_path(config_name: str) -> str:
    """Get path for system configuration file.

    Args:
        config_name: Configuration file name

    Returns:
        Absolute path to system config file

    Examples:
        >>> get_system_config_path("settings.json")
        '/persistent/.context/system/settings.json'

    """
    safe_filename = sanitize_filename(config_name)
    return f"{get_context_root()}/system/{safe_filename}"


# ============ Session Context Layout ============


def get_context_session_dir(session_id: str) -> str:
    """Get context directory for a session.

    Args:
        session_id: Session identifier (e.g., chat_id)

    Returns:
        Absolute path to session context directory

    Examples:
        >>> get_context_session_dir("chat_abc123")
        '/persistent/.context/chat_abc123'

    """
    safe_session = sanitize_path_segment(session_id)
    return f"{get_context_root()}/{safe_session}"


def get_context_subdir(session_id: str, subdir: ContextSubdir) -> str:
    """Get context subdirectory for a session.

    Args:
        session_id: Session identifier
        subdir: Subdirectory type ('compacted', 'scratchpad')

    Returns:
        Absolute path to context subdirectory

    Examples:
        >>> get_context_subdir("chat_abc123", "compacted")
        '/persistent/.context/chat_abc123/compacted'

    """
    session_dir = get_context_session_dir(session_id)
    subdir_name = CONTEXT_SUBDIRS[subdir]
    return f"{session_dir}/{subdir_name}"


def get_context_file_path(
    session_id: str,
    subdir: ContextSubdir,
    filename: str,
) -> str:
    """Get full path for a context file.

    Args:
        session_id: Session identifier
        subdir: Subdirectory type
        filename: File name

    Returns:
        Absolute path to context file

    Examples:
        >>> get_context_file_path("chat_abc", "compacted", "tool_output.txt")
        '/persistent/.context/chat_abc/compacted/tool_output.txt'

    """
    subdir_path = get_context_subdir(session_id, subdir)
    safe_filename = sanitize_filename(filename)
    return f"{subdir_path}/{safe_filename}"


def get_workspace_relative_path(absolute_path: str) -> str:
    """Convert absolute path to workspace-relative path.

    Args:
        absolute_path: Absolute path in execution environment

    Returns:
        Workspace-relative path (without leading /)

    Examples:
        >>> get_workspace_relative_path("/persistent/.context/chat_abc/compacted/file.txt")
        '.context/chat_abc/compacted/file.txt'
        >>> get_workspace_relative_path("/persistent/workspace/project/file.py")
        'workspace/project/file.py'

    """
    persistent_root = get_persistent_root()
    if absolute_path.startswith(persistent_root + "/"):
        return absolute_path[len(persistent_root) + 1 :]
    if absolute_path.startswith(LEGACY_WORKSPACE_ROOT + "/"):
        return absolute_path[len(LEGACY_WORKSPACE_ROOT) + 1 :]
    return absolute_path.lstrip("/")


def ensure_context_dir_exists(
    session_id: str,
    subdir: ContextSubdir | None = None,
) -> str:
    """Ensure context directory exists, create if needed.

    Args:
        session_id: Session identifier
        subdir: Optional subdirectory type

    Returns:
        Absolute path to created directory

    Examples:
        >>> ensure_context_dir_exists("chat_abc123")
        '/persistent/.context/chat_abc123'
        >>> ensure_context_dir_exists("chat_abc123", "compacted")
        '/persistent/.context/chat_abc123/compacted'

    """
    if subdir:
        dir_path = get_context_subdir(session_id, subdir)
    else:
        dir_path = get_context_session_dir(session_id)

    Path(dir_path).mkdir(parents=True, exist_ok=True)
    return dir_path


# ============ Path Sanitization ============


def sanitize_path_segment(segment: str) -> str:
    """Sanitize path segment to prevent path traversal attacks.

    Args:
        segment: Path segment (e.g., session_id, tool_name)

    Returns:
        Sanitized segment (alphanumeric + _ - only)

    Examples:
        >>> sanitize_path_segment("chat_abc123")
        'chat_abc123'
        >>> sanitize_path_segment("../../../etc/passwd")
        'etc_passwd'
        >>> sanitize_path_segment("tool@name#123")
        'tool_name_123'

    """
    cleaned = "".join(c if c.isalnum() or c in "_-" else "_" for c in segment)
    sanitized = (cleaned[:64] or "default").strip("_")
    return sanitized if sanitized else "default"


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and special characters.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename

    Examples:
        >>> sanitize_filename("report.txt")
        'report.txt'
        >>> sanitize_filename("../../../etc/passwd")
        'etc_passwd'
        >>> sanitize_filename("file@#$%.txt")
        'file____.txt'

    """
    name = os.path.basename(filename)
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    sanitized = (cleaned[:255] or "file.txt").strip("_")
    return sanitized if sanitized else "file.txt"


# ============ Path Validation ============


def is_context_path(path: str) -> bool:
    """Check if path is within context directory.

    Args:
        path: Absolute or relative path

    Returns:
        True if path is context path, False otherwise

    Examples:
        >>> is_context_path("/persistent/.context/chat_abc/compacted/file.txt")
        True
        >>> is_context_path("/persistent/workspace/project/file.py")
        False

    """
    abs_path = os.path.abspath(path)
    context_root = get_context_root()
    return abs_path.startswith(context_root + "/") or abs_path == context_root

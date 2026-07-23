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
    ├── workspace/                    ← User workspace
    │   ├── projects/                ← User projects
    │   ├── artifacts/               ← Agent-generated artifacts
    │   └── skills/                  ← Custom skills
    └── .claude/                     ← Legacy system configuration

Compatibility:
    Supports both /persistent and /workspace paths for flexible deployment.

[INPUT]
- (none)

[OUTPUT]
- get_compacted_output_path: Get path for compacted tool output (auto-generates UUID).
- get_content_addressed_compacted_output_path: Get stable path for compacted tool output.
- get_content_addressed_compacted_restore_map_path: Get sidecar path for targeted restore hints.
- get_context_archive_sidecar_path_candidates: Resolve archive sidecar candidates for tool path forms.
- get_evicted_output_path: Get path for evicted large bash output (auto-generates UU...
- get_scratchpad_path: Get path for agent scratchpad file.
- get_snapshot_path: Get path for pre-compression conversation snapshot (auto-...
- get_system_config_path: Get path for system configuration file.

[POS]
Unified execution path constants and utilities.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ============ Core Path Constants ============

# Persistent volume mount point (Docker Volume)
PERSISTENT_ROOT = "/persistent"

# Workspace root (user files, projects, artifacts)
WORKSPACE_ROOT = f"{PERSISTENT_ROOT}/workspace"

# Context offload root (compressed tool outputs, scratchpad)
CONTEXT_ROOT = f"{PERSISTENT_ROOT}/.context"

# Artifacts root (agent-generated files)
ARTIFACTS_ROOT = f"{WORKSPACE_ROOT}/artifacts"

# Memories root (memory storage)
MEMORIES_ROOT = f"{PERSISTENT_ROOT}/.memories"

# System configuration root
SYSTEM_CONFIG_ROOT = f"{CONTEXT_ROOT}/system"

# Legacy system configuration root (for backward compatibility)
LEGACY_SYSTEM_CONFIG_ROOT = f"{PERSISTENT_ROOT}/.claude"

# Alternative workspace path for compatibility
LEGACY_WORKSPACE_ROOT = "/workspace"


# ============ Context Subdirectories ============

ContextSubdir = Literal["compacted", "scratchpad", "snapshots", "evicted"]

CONTEXT_SUBDIRS: dict[ContextSubdir, str] = {
    "compacted": "compacted",  # Compressed tool outputs
    "scratchpad": "scratchpad",  # Agent active externalization
    "snapshots": "snapshots",  # Pre-compression full conversation snapshots
    "evicted": "evicted",  # Large tool/web output spill files (UECD)
}


# ============ Specialized Path Functions ============


def get_compacted_output_path(session_id: str, tool_name: str, compressed: bool = False) -> str:
    """Get path for compacted tool output (auto-generates UUID).

    Args:
        session_id: Session identifier (e.g., chat_id)
        tool_name: Tool name (e.g., 'web_search', 'bash')
        compressed: Whether the file will be gzip-compressed (affects extension)

    Returns:
        Absolute path to compacted output file

    Examples:
        >>> get_compacted_output_path("chat_abc123", "web_search")
        '/persistent/.context/chat_abc123/compacted/web_search_a3f5c8d1.txt'
        >>> get_compacted_output_path("chat_abc123", "web_search", compressed=True)
        '/persistent/.context/chat_abc123/compacted/web_search_a3f5c8d1.txt.gz'

    """
    safe_session = _sanitize_path_segment(session_id)
    safe_tool = _sanitize_path_segment(tool_name)
    unique_id = uuid.uuid4().hex[:8]
    ext = ".txt.gz" if compressed else ".txt"
    filename = f"{safe_tool}_{unique_id}{ext}"
    return f"{CONTEXT_ROOT}/{safe_session}/compacted/{filename}"


def get_content_addressed_compacted_output_path(
    session_id: str,
    tool_name: str,
    content_sha256: str,
    content_size_bytes: int,
    compressed: bool = False,
) -> str:
    """Get stable session-scoped path for content-addressed compacted output.

    The hash is scoped under the session directory, so it provides retry safety
    without introducing cross-user or cross-session deduplication.
    """
    safe_session = _sanitize_path_segment(session_id)
    safe_tool = _sanitize_path_segment(tool_name)
    normalized_hash = "".join(ch for ch in content_sha256.lower() if ch in "0123456789abcdef")
    if len(normalized_hash) != 64:
        raise ValueError("content_sha256 must be a 64-character hexadecimal digest")

    safe_size = max(content_size_bytes, 0)
    prefix = normalized_hash[:2]
    ext = ".txt.gz" if compressed else ".txt"
    filename = f"{safe_tool}_{normalized_hash[:24]}_{safe_size}{ext}"
    return f"{CONTEXT_ROOT}/{safe_session}/compacted/sha256/{prefix}/{filename}"


def get_content_addressed_compacted_metadata_path(
    session_id: str,
    tool_name: str,
    content_sha256: str,
    content_size_bytes: int,
    compressed: bool = False,
) -> str:
    """Get stable metadata path for content-addressed compacted output."""
    return (
        get_content_addressed_compacted_output_path(
            session_id,
            tool_name,
            content_sha256,
            content_size_bytes,
            compressed=compressed,
        )
        + ".meta.json"
    )


def get_content_addressed_compacted_restore_map_path(
    session_id: str,
    tool_name: str,
    content_sha256: str,
    content_size_bytes: int,
    compressed: bool = False,
) -> str:
    """Get stable restore-map sidecar path for content-addressed compacted output."""
    return (
        get_content_addressed_compacted_output_path(
            session_id,
            tool_name,
            content_sha256,
            content_size_bytes,
            compressed=compressed,
        )
        + ".restore.json"
    )


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
    from myrm_agent_harness.agent.context_management.infra.evicted_content import (
        build_evicted_basename,
    )

    safe_session = _sanitize_path_segment(session_id)
    filename = build_evicted_basename(source, ext=ext)
    return f"{CONTEXT_ROOT}/{safe_session}/evicted/{filename}"


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
    safe_session = _sanitize_path_segment(session_id)
    safe_filename = _sanitize_filename(filename)
    return f"{CONTEXT_ROOT}/{safe_session}/scratchpad/{safe_filename}"


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
    safe_session = _sanitize_path_segment(session_id)
    timestamp = int(time.time())
    unique_id = uuid.uuid4().hex[:8]
    ext = ".jsonl.gz" if compressed else ".jsonl"
    filename = f"{timestamp}_{unique_id}{ext}"
    return f"{CONTEXT_ROOT}/{safe_session}/snapshots/{filename}"


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
    safe_filename = _sanitize_filename(config_name)
    return f"{SYSTEM_CONFIG_ROOT}/{safe_filename}"


# ============ Legacy Path Utilities (for backward compatibility) ============


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
    safe_session = _sanitize_path_segment(session_id)
    return f"{CONTEXT_ROOT}/{safe_session}"


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
    safe_filename = _sanitize_filename(filename)
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
    if absolute_path.startswith(PERSISTENT_ROOT + "/"):
        return absolute_path[len(PERSISTENT_ROOT) + 1 :]
    if absolute_path.startswith(LEGACY_WORKSPACE_ROOT + "/"):
        return absolute_path[len(LEGACY_WORKSPACE_ROOT) + 1 :]
    return absolute_path.lstrip("/")


def get_context_archive_sidecar_path_candidates(
    archive_path: str,
    *,
    suffix: str = ".restore.json",
) -> tuple[str, ...]:
    """Return stable sidecar candidates for archive path forms exposed to tools.

    Archive references may be surfaced as absolute sandbox paths, `/persistent`-
    relative paths, workspace-relative paths, or `.context/...` tool arguments.
    The candidates are intentionally ordered from the literal argument to the
    canonical persistent locations so local tests and sandbox runtime both work.
    """
    raw_path = archive_path.strip()
    if not raw_path:
        return ()

    archive_candidates: list[str] = [raw_path]
    is_absolute = raw_path.startswith("/")
    if raw_path.startswith(f"{PERSISTENT_ROOT}/"):
        archive_candidates.append(get_workspace_relative_path(raw_path))
    elif raw_path.startswith(".context/") or raw_path.startswith("workspace/"):
        archive_candidates.append(f"{PERSISTENT_ROOT}/{raw_path}")
    elif raw_path.startswith(f"{LEGACY_WORKSPACE_ROOT}/"):
        archive_candidates.append(f"{WORKSPACE_ROOT}/{raw_path[len(LEGACY_WORKSPACE_ROOT) + 1 :]}")
    elif not is_absolute:
        archive_candidates.extend((f"{WORKSPACE_ROOT}/{raw_path}", f"{PERSISTENT_ROOT}/{raw_path}"))

    sidecars: list[str] = []
    seen: set[str] = set()
    for candidate in archive_candidates:
        sidecar = f"{candidate}{suffix}"
        if sidecar in seen:
            continue
        seen.add(sidecar)
        sidecars.append(sidecar)
    return tuple(sidecars)


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


def _sanitize_path_segment(segment: str) -> str:
    """Sanitize path segment to prevent path traversal attacks.

    Args:
        segment: Path segment (e.g., session_id, tool_name)

    Returns:
        Sanitized segment (alphanumeric + _ - only)

    Examples:
        >>> _sanitize_path_segment("chat_abc123")
        'chat_abc123'
        >>> _sanitize_path_segment("../../../etc/passwd")
        'etc_passwd'
        >>> _sanitize_path_segment("tool@name#123")
        'tool_name_123'

    """
    cleaned = "".join(c if c.isalnum() or c in "_-" else "_" for c in segment)
    sanitized = (cleaned[:64] or "default").strip("_")
    return sanitized if sanitized else "default"


def _sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and special characters.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename

    Examples:
        >>> _sanitize_filename("report.txt")
        'report.txt'
        >>> _sanitize_filename("../../../etc/passwd")
        'etc_passwd'
        >>> _sanitize_filename("file@#$%.txt")
        'file____.txt'

    """
    name = os.path.basename(filename)
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    sanitized = (cleaned[:255] or "file.txt").strip("_")
    return sanitized if sanitized else "file.txt"


# ============ Path Validation ============


def is_persistent_path(path: str) -> bool:
    """Check if path is within persistent volume.

    Args:
        path: Absolute or relative path

    Returns:
        True if path is persistent, False otherwise

    Examples:
        >>> is_persistent_path("/persistent/.context/file.txt")
        True
        >>> is_persistent_path("/tmp/temp.txt")
        False

    """
    abs_path = os.path.abspath(path)
    return abs_path.startswith(PERSISTENT_ROOT + "/") or abs_path == PERSISTENT_ROOT


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
    return abs_path.startswith(CONTEXT_ROOT + "/") or abs_path == CONTEXT_ROOT


# Cached function references to avoid repeated imports
_cached_get_current_chat_id: Callable[[], str | None] | None = None
_cached_get_file_access_tracker: Callable[[], Coroutine[None, None, object]] | None = None


async def track_context_file_access_if_needed(file_path: str) -> None:
    """Track context file access if in agent session context.

    Automatically records file access to FileAccessTracker when:
    1. File is a context file (in /persistent/.context/)
    2. Currently in an agent session (has session_id)

    Args:
        file_path: File path to potentially track

    Note:
        Fails silently if tracking is not available or not in session context.
        This ensures file operations work even without tracking infrastructure.

    """
    global _cached_get_current_chat_id, _cached_get_file_access_tracker

    if not is_context_path(file_path):
        return

    try:
        # Lazy import and cache
        if _cached_get_current_chat_id is None:
            from myrm_agent_harness.agent.context_management.infra.session_lock import (
                get_current_chat_id,
            )

            _cached_get_current_chat_id = get_current_chat_id

        chat_id = _cached_get_current_chat_id()
        if not chat_id:
            return

        if _cached_get_file_access_tracker is None:
            from myrm_agent_harness.runtime.context.file_access_tracker import (
                get_file_access_tracker,
            )

            _cached_get_file_access_tracker = get_file_access_tracker

        tracker = await _cached_get_file_access_tracker()
        await tracker.record_access(file_path, session_id=chat_id)
    except Exception as exc:
        logger.debug(f"Failed to track context file access for {file_path}: {exc}")

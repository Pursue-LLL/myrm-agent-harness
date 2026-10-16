"""Path builders for compacted tool-output archives and their sidecar files.

[INPUT]
- runtime.paths.execution_paths::get_context_root, get_persistent_root, get_workspace_root,
  get_workspace_relative_path, sanitize_path_segment (POS: roots in effect and traversal-safe segments)

[OUTPUT]
- get_compacted_output_path: Path for a compacted tool output (auto-generates UUID).
- get_content_addressed_compacted_output_path: Stable session-scoped path for a compacted output.
- get_content_addressed_compacted_metadata_path: Metadata sidecar of a content-addressed output.
- get_content_addressed_compacted_restore_map_path: Restore-map sidecar of a content-addressed output.
- get_context_archive_sidecar_path_candidates: Sidecar candidates for the archive path forms tools see.

[POS]
Archive-side half of the execution path SSOT; session layout and roots live in execution_paths.
"""

from __future__ import annotations

import uuid

from myrm_agent_harness.runtime.paths.execution_paths import (
    LEGACY_WORKSPACE_ROOT,
    get_context_root,
    get_persistent_root,
    get_workspace_relative_path,
    get_workspace_root,
    sanitize_path_segment,
)


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
    safe_session = sanitize_path_segment(session_id)
    safe_tool = sanitize_path_segment(tool_name)
    unique_id = uuid.uuid4().hex[:8]
    ext = ".txt.gz" if compressed else ".txt"
    filename = f"{safe_tool}_{unique_id}{ext}"
    return f"{get_context_root()}/{safe_session}/compacted/{filename}"


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
    safe_session = sanitize_path_segment(session_id)
    safe_tool = sanitize_path_segment(tool_name)
    normalized_hash = "".join(ch for ch in content_sha256.lower() if ch in "0123456789abcdef")
    if len(normalized_hash) != 64:
        raise ValueError("content_sha256 must be a 64-character hexadecimal digest")

    safe_size = max(content_size_bytes, 0)
    prefix = normalized_hash[:2]
    ext = ".txt.gz" if compressed else ".txt"
    filename = f"{safe_tool}_{normalized_hash[:24]}_{safe_size}{ext}"
    return f"{get_context_root()}/{safe_session}/compacted/sha256/{prefix}/{filename}"


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

    persistent_root = get_persistent_root()
    workspace_root = get_workspace_root()
    archive_candidates: list[str] = [raw_path]
    is_absolute = raw_path.startswith("/")
    if raw_path.startswith(f"{persistent_root}/"):
        archive_candidates.append(get_workspace_relative_path(raw_path))
    elif raw_path.startswith(".context/") or raw_path.startswith("workspace/"):
        archive_candidates.append(f"{persistent_root}/{raw_path}")
    elif raw_path.startswith(f"{LEGACY_WORKSPACE_ROOT}/"):
        archive_candidates.append(f"{workspace_root}/{raw_path[len(LEGACY_WORKSPACE_ROOT) + 1 :]}")
    elif not is_absolute:
        archive_candidates.extend((f"{workspace_root}/{raw_path}", f"{persistent_root}/{raw_path}"))

    sidecars: list[str] = []
    seen: set[str] = set()
    for candidate in archive_candidates:
        sidecar = f"{candidate}{suffix}"
        if sidecar in seen:
            continue
        seen.add(sidecar)
        sidecars.append(sidecar)
    return tuple(sidecars)

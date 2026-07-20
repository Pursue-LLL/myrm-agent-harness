"""Secure ZIP extraction with defense-in-depth.

[INPUT]
- backends.skills.scanning.archive_security::ArchiveSecurityError (POS: Typed archive-security error contract shared across validation/extraction layers.)

[OUTPUT]
- safe_extract_zip(): extract ZIP content with Zip Bomb / symlink / path traversal defense
- MAX_ZIP_ENTRY_COUNT: default archive member-count hard limit shared by validation/extraction layers

[POS]
Framework-level ZIP security utility. Business layers call this instead of
implementing their own extraction logic.

Defenses:
1. Zip Bomb: reject when compression ratio exceeds threshold
2. Entry-count limit: reject archives with too many members
3. Total size limit: prevent disk exhaustion
4. Symlink detection: skip symlink entries to block directory escape
5. Path traversal: reject entries containing .. components
6. Absolute path: reject entries starting with / or \\ (blocks pathlib join escape)
7. Windows drive prefix: reject entries like C:\\ or D:\\ (blocks PureWindowsPath join escape)
8. Executable-binary detection: reject archives containing ELF/PE/Mach-O members
"""

from __future__ import annotations

import io
import logging
import zipfile
from collections.abc import Callable

from myrm_agent_harness.backends.skills.scanning.archive_security import (
    ArchiveSecurityCode,
    ArchiveSecurityError,
    ArchiveSecurityViolation,
    is_executable_binary_content,
    log_archive_security_violation,
)

logger = logging.getLogger(__name__)

_MAX_COMPRESSION_RATIO = 100
_MAX_TOTAL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_ZIP_ENTRY_COUNT = 4096
_SYMLINK_TYPE_MASK = 0o170000
_SYMLINK_TYPE_FLAG = 0o120000


def safe_extract_zip(
    zip_content: bytes,
    *,
    max_compression_ratio: int = _MAX_COMPRESSION_RATIO,
    max_total_bytes: int = _MAX_TOTAL_UNCOMPRESSED_BYTES,
    max_entries: int = MAX_ZIP_ENTRY_COUNT,
    strip_top_dir: bool = True,
    forbidden_check: Callable[[str], bool] | None = None,
) -> dict[str, bytes]:
    """Extract ZIP content with security hardening.

    This is a framework-level security utility. Business layers should call
    this instead of implementing their own extraction logic.

    Args:
        zip_content: Raw ZIP bytes
        max_compression_ratio: Maximum allowed compression ratio (default 100:1)
        max_total_bytes: Maximum total uncompressed size in bytes (default 50 MB)
        max_entries: Maximum allowed member count before extraction (default 4096)
        strip_top_dir: If True, strip the top-level directory from paths
        forbidden_check: Optional callback to filter out forbidden files by path

    Returns:
        Mapping of relative file paths to their contents

    Raises:
        ValueError: If compression ratio, entry count, or size limits are exceeded
    """
    compressed_size = len(zip_content)

    with zipfile.ZipFile(io.BytesIO(zip_content), "r") as zf:
        infos = zf.infolist()
        total_uncompressed = sum(info.file_size for info in infos)

        _check_zip_bomb(compressed_size, total_uncompressed, max_compression_ratio)
        _check_entry_count(len(infos), max_entries)
        _check_total_size(total_uncompressed, max_total_bytes)

        file_contents: dict[str, bytes] = {}

        for entry in infos:
            if entry.filename.endswith("/"):
                continue

            if _is_symlink(entry):
                logger.warning("Skipping symlink entry: %s", entry.filename)
                continue

            relative_path = _resolve_path(entry.filename, strip_top_dir)

            if _has_path_traversal(relative_path):
                logger.warning("Skipping path traversal entry: %s", entry.filename)
                continue

            entry_bytes = zf.read(entry.filename)
            _check_executable_binary_member(relative_path, entry_bytes)
            if forbidden_check is not None and forbidden_check(relative_path):
                continue
            file_contents[relative_path] = entry_bytes

    return file_contents


def _check_zip_bomb(compressed: int, uncompressed: int, max_ratio: int) -> None:
    if compressed > 0 and uncompressed / compressed > max_ratio:
        ratio = uncompressed / compressed
        violation = ArchiveSecurityViolation(
            code=ArchiveSecurityCode.COMPRESSION_RATIO_EXCEEDED,
            source="safe_extract_zip",
            actual=ratio,
            limit=max_ratio,
        )
        log_archive_security_violation(logger, violation)
        raise ArchiveSecurityError(
            violation,
            f"Zip Bomb detected: compression ratio {ratio:.0f}:1 exceeds {max_ratio}:1 limit",
        )


def _check_total_size(total: int, max_bytes: int) -> None:
    if total > max_bytes:
        violation = ArchiveSecurityViolation(
            code=ArchiveSecurityCode.TOTAL_SIZE_EXCEEDED,
            source="safe_extract_zip",
            actual=total,
            limit=max_bytes,
        )
        log_archive_security_violation(logger, violation)
        raise ArchiveSecurityError(
            violation,
            (
                f"Total uncompressed size {total / 1024 / 1024:.1f} MB "
                f"exceeds {max_bytes / 1024 / 1024:.0f} MB limit"
            ),
        )


def _check_entry_count(total_entries: int, max_entries: int) -> None:
    if total_entries > max_entries:
        violation = ArchiveSecurityViolation(
            code=ArchiveSecurityCode.ENTRY_LIMIT_EXCEEDED,
            source="safe_extract_zip",
            actual=total_entries,
            limit=max_entries,
        )
        log_archive_security_violation(logger, violation)
        raise ArchiveSecurityError(
            violation,
            f"ZIP contains too many entries ({total_entries} > {max_entries})",
        )


def _check_executable_binary_member(path: str, content: bytes) -> None:
    if is_executable_binary_content(content):
        violation = ArchiveSecurityViolation(
            code=ArchiveSecurityCode.EXECUTABLE_BINARY_DETECTED,
            source="safe_extract_zip",
        )
        log_archive_security_violation(logger, violation)
        raise ArchiveSecurityError(
            violation,
            f"ZIP contains executable binary member: {path}",
        )


def _is_symlink(entry: zipfile.ZipInfo) -> bool:
    unix_attrs = entry.external_attr >> 16
    return unix_attrs & _SYMLINK_TYPE_MASK == _SYMLINK_TYPE_FLAG


def _resolve_path(filename: str, strip_top_dir: bool) -> str:
    if strip_top_dir:
        parts = filename.split("/", 1)
        return parts[1] if len(parts) > 1 else parts[0]
    return filename


def _has_path_traversal(path: str) -> bool:
    if path.startswith(("/", "\\")):
        return True
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        return True
    return ".." in path.split("/")

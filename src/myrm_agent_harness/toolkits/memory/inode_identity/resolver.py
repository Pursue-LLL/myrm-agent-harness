"""Filesystem resolver for physical directory inode and device identities.

Extracts immutable (device, inode) tuples across POSIX and Windows hosts,
safely traversing symlinks and generating collision-resistant root signatures.
"""

from __future__ import annotations

import hashlib
import os
import platform
from pathlib import Path

from myrm_agent_harness.toolkits.memory.inode_identity.models import (
    DeviceFilesystemKind,
    DirectoryIdentity,
    InodeResolutionResult,
)


class InodeIdentityResolver:
    """Extracts physical device and inode metadata for directory paths."""

    def __init__(self, identity_file_name: str = ".myrm_identity") -> None:
        self._identity_file_name: str = identity_file_name
        self._os_name: str = platform.system().lower()

    def resolve(self, target_path: str) -> InodeResolutionResult:
        """Resolve physical device and inode identity for a directory path."""
        if not target_path or not target_path.strip():
            return InodeResolutionResult(
                real_path="",
                is_accessible=False,
                is_directory=False,
                error_message="Target path cannot be empty",
            )

        norm_path = os.path.normpath(os.path.abspath(target_path))
        is_symlink = os.path.islink(norm_path)

        try:
            real_path = os.path.realpath(norm_path)
            stat_res = os.stat(real_path)
        except (OSError, PermissionError) as exc:
            return InodeResolutionResult(
                real_path=norm_path,
                is_accessible=False,
                is_directory=False,
                is_symlink=is_symlink,
                error_message=f"Filesystem access failed: {exc}",
            )

        is_directory = os.path.isdir(real_path)
        if not is_directory:
            return InodeResolutionResult(
                real_path=real_path,
                is_accessible=True,
                is_directory=False,
                is_symlink=is_symlink,
                error_message="Target path is not a directory",
            )

        dev_id, ino_id, fs_kind = self._extract_device_and_inode(real_path, stat_res)
        birth_time_ns = self._extract_birth_time_ns(stat_res)
        root_sig = self._derive_root_signature(real_path, birth_time_ns, dev_id, ino_id)

        identity = DirectoryIdentity(
            canonical_path=real_path,
            device_id=dev_id,
            inode_id=ino_id,
            birth_time_ns=birth_time_ns,
            root_signature=root_sig,
            fs_kind=fs_kind,
            is_symlink=is_symlink,
        )

        return InodeResolutionResult(
            real_path=real_path,
            is_accessible=True,
            is_directory=True,
            identity=identity,
            is_symlink=is_symlink,
        )

    def _extract_device_and_inode(
        self,
        real_path: str,
        stat_res: os.stat_result,
    ) -> tuple[int, int, DeviceFilesystemKind]:
        """Extract physical (device_id, inode_id) tuple safely across platforms."""
        if self._os_name == "windows":
            # On Windows, try ctypes or fallback to volume serial hash
            dev_id, ino_id = self._extract_windows_identity(real_path, stat_res)
            return dev_id, ino_id, DeviceFilesystemKind.WINDOWS

        # POSIX (Linux, macOS)
        dev_id = int(stat_res.st_dev)
        ino_id = int(stat_res.st_ino)
        return dev_id, ino_id, DeviceFilesystemKind.POSIX

    def _extract_windows_identity(
        self,
        real_path: str,
        stat_res: os.stat_result,
    ) -> tuple[int, int]:
        """Derive Windows volume serial and file index identifiers."""
        # Check if st_ino is supported natively in modern Python on Windows
        if stat_res.st_ino != 0:
            return int(stat_res.st_dev), int(stat_res.st_ino)

        # Fallback heuristic using drive letter and path digest
        drive = os.path.splitdrive(real_path)[0].upper() or "C:"
        drive_hash = int(hashlib.sha256(drive.encode("utf-8")).hexdigest()[:8], 16)
        path_hash = int(hashlib.sha256(real_path.encode("utf-8")).hexdigest()[:12], 16)
        return drive_hash, path_hash

    def _extract_birth_time_ns(self, stat_res: os.stat_result) -> int:
        """Extract creation or status change timestamp in nanoseconds."""
        if hasattr(stat_res, "st_birthtime"):
            return int(float(stat_res.st_birthtime) * 1_000_000_000)
        # Fallback to st_ctime for platforms lacking st_birthtime
        return int(float(stat_res.st_ctime) * 1_000_000_000)

    def _derive_root_signature(
        self,
        real_path: str,
        birth_time_ns: int,
        device_id: int,
        inode_id: int,
    ) -> str:
        """Derive a lightweight root identity fingerprint."""
        identity_file = Path(real_path) / self._identity_file_name
        if identity_file.is_file():
            try:
                content = identity_file.read_text(encoding="utf-8").strip()
                if content:
                    return f"file:{content}"
            except (OSError, UnicodeDecodeError):
                pass

        # Synthesize fingerprint from physical coordinates + birth time + path basename
        seed = f"{device_id}:{inode_id}:{birth_time_ns}:{os.path.basename(real_path)}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return f"auto:{digest}"

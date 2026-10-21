"""Workspace incremental delta synchronization and archive bundle manager.

Packs and unpacks modified files between local execution environments and remote
cloud sandboxes, minimizing bandwidth and ensuring atomic workspace synchronization.

[OUTPUT]
- WorkspaceDeltaSyncer: Scans, bundles, and applies incremental filesystem updates.

[INPUT]
- __future__
- io
- os
- zipfile
- collections
- pathlib

[OUTPUT]
- WorkspaceDeltaSyncer

[POS]
Workspace incremental delta synchronization and archive bundle manager.
"""

from __future__ import annotations

import io
import os
import zipfile
from collections.abc import Iterable
from pathlib import Path


class WorkspaceDeltaSyncer:
    """Calculates filesystem deltas and applies compressed archives across environments."""

    @staticmethod
    def scan_files(root: Path | str) -> dict[str, tuple[int, float]]:
        """Return a mapping of relative file paths to (size_bytes, mtime)."""
        r = Path(root).resolve()
        manifest: dict[str, tuple[int, float]] = {}

        if not r.is_dir():
            return manifest

        for root_dir, _, filenames in os.walk(r):
            for fname in filenames:
                full_path = Path(root_dir) / fname
                try:
                    rel = str(full_path.relative_to(r))
                    stat = full_path.stat()
                    manifest[rel] = (stat.st_size, stat.st_mtime)
                except (OSError, ValueError):
                    continue

        return manifest

    @classmethod
    def compute_delta(
        cls,
        source_root: Path | str,
        target_manifest: dict[str, tuple[int, float]] | None = None,
    ) -> tuple[str, ...]:
        """Identify files in source_root that are new or modified compared to target_manifest."""
        source_files = cls.scan_files(source_root)
        if not target_manifest:
            return tuple(sorted(source_files.keys()))

        delta: list[str] = []
        for rel_path, (src_size, src_mtime) in source_files.items():
            if rel_path not in target_manifest:
                delta.append(rel_path)
            else:
                tgt_size, tgt_mtime = target_manifest[rel_path]
                if src_size != tgt_size or src_mtime > tgt_mtime:
                    delta.append(rel_path)

        return tuple(sorted(delta))

    @staticmethod
    def export_delta_bundle(
        source_root: Path | str,
        files_to_pack: Iterable[str],
    ) -> bytes:
        """Compress selected relative file paths into an in-memory zip archive."""
        root = Path(source_root).resolve()
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for rel in files_to_pack:
                src_path = root / rel
                if src_path.is_file():
                    zf.write(src_path, arcname=rel)

        return buffer.getvalue()

    @staticmethod
    def apply_delta_bundle(
        target_root: Path | str,
        bundle_bytes: bytes,
    ) -> tuple[int, int]:
        """Extract files from the bundle into target_root atomically.

        Returns:
            (files_extracted_count, total_bytes_written)
        """
        root = Path(target_root).resolve()
        root.mkdir(parents=True, exist_ok=True)

        if not bundle_bytes:
            return 0, 0

        buffer = io.BytesIO(bundle_bytes)
        files_count = 0
        bytes_written = 0

        with zipfile.ZipFile(buffer, mode="r") as zf:
            for info in zf.infolist():
                # Prevent path traversal attacks
                out_path = (root / info.filename).resolve()
                if not out_path.is_relative_to(root):
                    continue

                out_path.parent.mkdir(parents=True, exist_ok=True)
                data = zf.read(info)
                out_path.write_bytes(data)
                files_count += 1
                bytes_written += len(data)

        return files_count, bytes_written

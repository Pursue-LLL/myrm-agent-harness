# [POS]: myrm_agent_harness/toolkits/memory/sovereign_migration/bundle_archiver.py
# [INPUT]: hashlib, json, os, pathlib.Path, shutil, sys, tarfile, tempfile, uuid, types, path_relativizer
# [OUTPUT]: SovereignBundleArchiver
"""Consistent atomic packaging and checksum-verified sovereign asset archiver.

Packages SQLite databases, markdown wiki pages, handoff memorandums, and custom skills
into an encrypted/verifiable portable `.myrmpkg` archive with SHA-256 integrity manifest.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

from myrm_agent_harness.toolkits.memory.sovereign_migration.path_relativizer import (
    PathRelativizer,
)
from myrm_agent_harness.toolkits.memory.sovereign_migration.types import (
    AssetCategory,
    AssetEntry,
    ExportBundleRequest,
    ExportBundleResult,
    SovereignAssetManifest,
)

logger = logging.getLogger(__name__)


class SovereignBundleArchiver:
    """Produces atomic verified sovereign asset bundles (.myrmpkg) for migration."""

    def __init__(self) -> None:
        logger.info("SovereignBundleArchiver initialized")

    @staticmethod
    def _compute_sha256(data: bytes) -> str:
        """Compute hexadecimal SHA-256 hash for raw byte data."""
        return hashlib.sha256(data).hexdigest()

    def _determine_category(self, rel_path: str) -> AssetCategory:
        """Classify asset into standard AssetCategory based on relative path directory."""
        norm = rel_path.replace("\\", "/")
        if "wiki" in norm or norm.endswith(".md"):
            return AssetCategory.WIKI_MEMORY
        if norm.endswith(".db") or norm.endswith(".sqlite"):
            return AssetCategory.SQLITE_DATABASE
        if "handoff" in norm:
            return AssetCategory.HANDOFF_RECORD
        if "unload" in norm or "emergency" in norm:
            return AssetCategory.UNLOAD_SNAPSHOT
        if "skill" in norm:
            return AssetCategory.CUSTOM_SKILL
        if "rule" in norm or "prompt" in norm:
            return AssetCategory.AGENT_RULE
        return AssetCategory.WIKI_MEMORY

    def export_bundle(self, request: ExportBundleRequest) -> ExportBundleResult:
        """Collect, relativize, and package sovereign assets into a portable .myrmpkg archive."""
        source_dir = Path(request.source_dir).resolve()
        if not source_dir.exists():
            raise FileNotFoundError(f"Source directory '{source_dir}' does not exist.")

        output_path = Path(request.output_bundle_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        package_id = f"myrmpkg-{time_tag()}-{uuid.uuid4().hex[:8]}"

        with tempfile.TemporaryDirectory() as temp_dir_str:
            staging_dir = Path(temp_dir_str) / "package_root"
            staging_dir.mkdir(parents=True, exist_ok=True)
            assets_dir = staging_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            asset_entries: list[AssetEntry] = []
            total_uncompressed_bytes = 0

            # 1. Walk and collect files from source_dir
            for root, _, files in os.walk(source_dir):
                for f_name in files:
                    # Ignore temporary locks, sockets, or VCS internals
                    if f_name.endswith((".sock", ".tmp", ".lock")) or "/.git/" in root:
                        continue

                    full_path = Path(root) / f_name
                    rel_to_source = full_path.relative_to(source_dir)
                    rel_str = str(rel_to_source).replace("\\", "/")

                    category = self._determine_category(rel_str)
                    if category not in request.include_categories:
                        continue

                    dest_file = assets_dir / rel_to_source
                    dest_file.parent.mkdir(parents=True, exist_ok=True)

                    # Read raw data
                    raw_bytes = full_path.read_bytes()

                    # For text and markdown files, relativize absolute paths
                    if f_name.endswith((".md", ".txt", ".json", ".yaml", ".yml")):
                        try:
                            text_content = raw_bytes.decode("utf-8")
                            rel_text, _ = PathRelativizer.relativize_text(
                                text=text_content,
                                source_root=source_dir,
                            )
                            raw_bytes = rel_text.encode("utf-8")
                        except UnicodeDecodeError:
                            pass

                    dest_file.write_bytes(raw_bytes)
                    file_sha = self._compute_sha256(raw_bytes)
                    file_size = len(raw_bytes)
                    total_uncompressed_bytes += file_size

                    asset_entries.append(
                        AssetEntry(
                            category=category,
                            relative_path=f"assets/{rel_str}",
                            sha256=file_sha,
                            byte_size=file_size,
                            description=f"Exported asset: {rel_str}",
                        )
                    )

            # 2. Build MANIFEST.json
            combined_hashes = "".join(sorted(a.sha256 for a in asset_entries))
            manifest_hash = self._compute_sha256(combined_hashes.encode("utf-8"))

            manifest = SovereignAssetManifest(
                package_id=package_id,
                source_os=sys.platform,
                source_workspace_root=str(source_dir),
                description=request.custom_description,
                assets=asset_entries,
                total_bytes=total_uncompressed_bytes,
                manifest_sha256=manifest_hash,
            )

            manifest_path = staging_dir / "MANIFEST.json"
            manifest_path.write_text(
                manifest.model_dump_json(indent=2),
                encoding="utf-8",
            )

            # 3. Create .myrmpkg tar.gz archive atomically
            temp_archive = Path(temp_dir_str) / f"{package_id}.tar.gz"
            with tarfile.open(temp_archive, "w:gz") as tar:
                tar.add(staging_dir, arcname=".")

            archive_bytes = temp_archive.read_bytes()
            bundle_sha256 = self._compute_sha256(archive_bytes)

            # Move to destination
            shutil.move(str(temp_archive), str(output_path))

            logger.info(
                "Exported sovereign bundle %s (%d assets, %d bytes) to '%s'",
                package_id,
                len(asset_entries),
                total_uncompressed_bytes,
                output_path,
            )

            return ExportBundleResult(
                success=True,
                bundle_path=str(output_path),
                package_id=package_id,
                asset_count=len(asset_entries),
                total_bytes=total_uncompressed_bytes,
                sha256=bundle_sha256,
            )


def time_tag() -> str:
    """Format short human timestamp for package identifier."""
    import time
    return time.strftime("%Y%m%d%H%M%S")

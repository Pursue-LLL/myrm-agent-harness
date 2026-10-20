"""Atomic unpacker, integrity validator, and path-remapping restorer for sovereign asset bundles.

Unpacks `.myrmpkg` packages, verifies SHA-256 checksums from MANIFEST.json,
dynamically remaps hardcoded paths using PathRelativizer, and restores digital assets.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.sovereign_migration.path_relativizer::PathRelativizer (POS: Dynamic path relativization
  and cross-machine absolute path remapping engine.)
- toolkits.memory.sovereign_migration.types::RestoreBundleRequest, RestoreBundleResult,
  SovereignAssetManifest (POS: Type definitions for sovereign asset bundle migration and cross-machine
  restore protocol.)

[OUTPUT]
- SovereignBundleRestorer: Restores sovereign asset packages with checksum integrity and path remapping.

[POS]
Atomic unpacker, integrity validator, and path-remapping restorer for sovereign asset bundles.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tarfile
import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.memory.sovereign_migration.path_relativizer import (
    PathRelativizer,
)
from myrm_agent_harness.toolkits.memory.sovereign_migration.types import (
    RestoreBundleRequest,
    RestoreBundleResult,
    SovereignAssetManifest,
)

logger = logging.getLogger(__name__)


class SovereignBundleRestorer:
    """Restores sovereign asset packages with checksum integrity and path remapping."""

    def __init__(self) -> None:
        logger.info("SovereignBundleRestorer initialized")

    @staticmethod
    def _compute_sha256(data: bytes) -> str:
        """Compute hexadecimal SHA-256 hash for raw byte data."""
        return hashlib.sha256(data).hexdigest()

    def restore_bundle(self, request: RestoreBundleRequest) -> RestoreBundleResult:
        """Unpack, verify SHA-256 checksums, remap paths, and restore files onto target host."""
        bundle_path = Path(request.bundle_path).resolve()
        if not bundle_path.exists() or not bundle_path.is_file():
            raise FileNotFoundError(f"Bundle file '{bundle_path}' does not exist.")

        target_dir = Path(request.target_destination_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        current_ws = Path(request.current_workspace_root).resolve()

        with tempfile.TemporaryDirectory() as temp_dir_str:
            unpack_dir = Path(temp_dir_str) / "unpacked"
            unpack_dir.mkdir(parents=True, exist_ok=True)

            # 1. Extract tar.gz archive safely
            with tarfile.open(bundle_path, "r:gz") as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(path=unpack_dir, filter="data")
                else:
                    tar.extractall(path=unpack_dir)  # noqa: S202

            manifest_file = unpack_dir / "MANIFEST.json"
            if not manifest_file.exists():
                raise ValueError("Corrupt bundle: MANIFEST.json is missing.")

            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            manifest = SovereignAssetManifest.model_validate(manifest_data)

            # 2. Verify all asset checksums
            remapped_count = 0
            restored_asset_paths: list[str] = []

            for entry in manifest.assets:
                extracted_asset_path = unpack_dir / entry.relative_path
                if not extracted_asset_path.exists():
                    raise ValueError(
                        f"Asset integrity failure: Manifest entry '{entry.relative_path}' missing from archive."
                    )

                asset_bytes = extracted_asset_path.read_bytes()
                computed_sha = self._compute_sha256(asset_bytes)
                if computed_sha != entry.sha256:
                    raise ValueError(
                        f"Checksum mismatch for asset '{entry.relative_path}': "
                        f"expected {entry.sha256}, got {computed_sha}"
                    )

                # Determine destination path relative to target_dir (stripping 'assets/' prefix)
                clean_rel = entry.relative_path
                if clean_rel.startswith("assets/"):
                    clean_rel = clean_rel[len("assets/") :]

                dest_file_path = target_dir / clean_rel
                dest_file_path.parent.mkdir(parents=True, exist_ok=True)

                if dest_file_path.exists() and not request.overwrite_existing:
                    logger.debug("Skipping existing file '%s' (overwrite disabled)", dest_file_path)
                    continue

                # 3. For text and markdown files, dynamically rebind workspace paths
                if dest_file_path.name.endswith((".md", ".txt", ".json", ".yaml", ".yml")):
                    try:
                        text_content = asset_bytes.decode("utf-8")
                        rebound_text, count = PathRelativizer.rebind_text(
                            text=text_content,
                            source_root=manifest.source_workspace_root,
                            target_root=current_ws,
                        )
                        remapped_count += count
                        asset_bytes = rebound_text.encode("utf-8")
                    except UnicodeDecodeError:
                        pass

                dest_file_path.write_bytes(asset_bytes)
                restored_asset_paths.append(clean_rel)

            logger.info(
                "Successfully restored bundle %s (%d assets restored, %d paths remapped) to '%s'",
                manifest.package_id,
                len(restored_asset_paths),
                remapped_count,
                target_dir,
            )

            return RestoreBundleResult(
                success=True,
                package_id=manifest.package_id,
                restored_assets=restored_asset_paths,
                remapped_paths_count=remapped_count,
                source_workspace_root=manifest.source_workspace_root,
                target_workspace_root=str(current_ws),
            )

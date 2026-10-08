"""
[POS] src/myrm_agent_harness/core/security/code_signing_gate/manifest_hasher.py
[INPUT] hashlib, typing, .types (PackageManifestEntry)
[OUTPUT] PackageManifestHasher

Calculates deterministic cryptographic SHA-256 digests of agent/skill package files
and verifies file integrity against declared manifest records.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib

from .types import PackageManifestEntry


class PackageManifestHasher:
    """Computes and verifies deterministic file asset digests for agent packages."""

    @staticmethod
    def hash_content(content: str | bytes) -> tuple[str, int]:
        """Compute SHA-256 hex digest and size for in-memory content."""
        data_bytes = content.encode("utf-8") if isinstance(content, str) else content
        sha256 = hashlib.sha256(data_bytes).hexdigest()
        return sha256, len(data_bytes)

    def build_manifest(
        self, files: dict[str, str | bytes]
    ) -> tuple[list[PackageManifestEntry], str]:
        """Compute sorted manifest entries and top-level canonical manifest digest."""
        entries: list[PackageManifestEntry] = []
        for path in sorted(files.keys()):
            sha256, size = self.hash_content(files[path])
            entries.append(
                PackageManifestEntry(
                    file_path=path,
                    sha256_hash=sha256,
                    size_bytes=size,
                )
            )

        canonical_digest = self.compute_canonical_digest(entries)
        return entries, canonical_digest

    @staticmethod
    def compute_canonical_digest(entries: list[PackageManifestEntry]) -> str:
        """Compute aggregate SHA-256 digest over sorted canonical manifest lines."""
        sorted_entries = sorted(entries, key=lambda e: e.file_path)
        canonical_str = "".join(
            f"{e.file_path}:{e.sha256_hash}:{e.size_bytes}\n" for e in sorted_entries
        )
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def verify_files_against_manifest(
        self,
        files: dict[str, str | bytes],
        declared_entries: list[PackageManifestEntry],
    ) -> tuple[bool, list[str]]:
        """Verify whether actual files strictly match declared manifest entries."""
        discrepancies: list[str] = []
        declared_map: dict[str, PackageManifestEntry] = {
            e.file_path: e for e in declared_entries
        }

        # Check for missing or modified files
        for path, entry in declared_map.items():
            if path not in files:
                discrepancies.append(f"Missing file declared in manifest: '{path}'")
                continue

            actual_hash, actual_size = self.hash_content(files[path])
            if actual_hash != entry.sha256_hash:
                discrepancies.append(
                    f"Digest mismatch for '{path}': expected {entry.sha256_hash}, got {actual_hash}"
                )
            elif actual_size != entry.size_bytes:
                discrepancies.append(
                    f"Size mismatch for '{path}': expected {entry.size_bytes}B, got {actual_size}B"
                )

        # Check for un-manifested injected files
        for path in files:
            if path not in declared_map:
                discrepancies.append(f"Unmanifested file injected into package: '{path}'")

        return len(discrepancies) == 0, discrepancies

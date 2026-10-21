"""Streaming cryptographic material integrity guard and input hash verifier.

Protects against silent data corruption, truncated uploads, and mismatched source files
during local-to-cloud handoffs (e.g. video frames, raw datasets, model weights).

[OUTPUT]
- MaterialIntegrityGuard: Chunked SHA-256 calculator and material consistency auditor.

[INPUT]
- __future__
- hashlib
- collections
- pathlib

[OUTPUT]
- MaterialIntegrityGuard

[POS]
Streaming cryptographic material integrity guard and input hash verifier.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from myrm_agent_harness.runtime.hot_handoff.handoff_types import MaterialDigest

_DEFAULT_CHUNK_SIZE: int = 65536  # 64 KB buffer for streaming I/O


class MaterialIntegrityGuard:
    """Computes streaming cryptographic hashes and verifies remote asset consistency."""

    @staticmethod
    def compute_file_digest(
        file_path: Path | str,
        relative_to: Path | str | None = None,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> MaterialDigest:
        """Calculate streaming SHA-256 and byte size without loading entire file into memory."""
        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Input material file not found: {p}")

        rel_path = (
            str(p.relative_to(Path(relative_to).resolve()))
            if relative_to is not None
            else p.name
        )

        hasher = hashlib.sha256()
        total_bytes = 0

        with p.open("rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
                total_bytes += len(chunk)

        return MaterialDigest(
            relative_path=rel_path,
            size_bytes=total_bytes,
            sha256_hash=hasher.hexdigest().lower(),
        )

    @classmethod
    def verify_single_material(
        cls,
        expected: MaterialDigest,
        candidate_file: Path | str,
    ) -> tuple[bool, str | None]:
        """Verify candidate file matches the expected size and SHA-256 checksum."""
        p = Path(candidate_file).resolve()
        if not p.is_file():
            return False, f"File missing at target location: {p}"

        # Fast path: check file size first to short-circuit expensive hashing
        actual_size = p.stat().st_size
        if actual_size != expected.size_bytes:
            return False, (
                f"Byte size mismatch for '{expected.relative_path}': "
                f"expected {expected.size_bytes} bytes, found {actual_size} bytes"
            )

        # Full cryptographic verification
        actual_digest = cls.compute_file_digest(p, relative_to=None)
        if actual_digest.sha256_hash != expected.sha256_hash.lower():
            return False, (
                f"SHA-256 digest mismatch for '{expected.relative_path}': "
                f"expected {expected.sha256_hash}, computed {actual_digest.sha256_hash}"
            )

        return True, None

    @classmethod
    def batch_verify(
        cls,
        expected_materials: Iterable[MaterialDigest],
        target_root: Path | str,
    ) -> tuple[bool, tuple[str, ...]]:
        """Verify an entire manifest of input materials against the target root directory."""
        root = Path(target_root).resolve()
        mismatches: list[str] = []

        for exp in expected_materials:
            candidate = root / exp.relative_path
            ok, err = cls.verify_single_material(exp, candidate)
            if not ok and err is not None:
                mismatches.append(err)

        return len(mismatches) == 0, tuple(mismatches)

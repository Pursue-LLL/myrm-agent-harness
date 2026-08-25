"""Unit tests for persistence integrity sealing and corruption detection.

[INPUT]
- myrm_agent_harness.core.security.integrity.seal (POS: IntegritySealer, SealManifest, IntegrityStatus, SEAL_FILENAME)

[OUTPUT]
- TestIntegritySealing: Test class validating manifest creation, tamper detection, missing files, and corruption quarantine triggers

[POS]
Harness core security integrity unit test suite.
"""

import json
from pathlib import Path

import pytest
from myrm_agent_harness.core.security.integrity.seal import (
    SEAL_FILENAME,
    SEAL_MAGIC_HEADER,
    IntegritySealer,
    IntegrityStatus,
    SealManifest,
)


class TestIntegritySealing:
    def test_create_and_verify_valid_manifest(self) -> None:
        session_id = "sess_12345"
        files = {
            "main.py": b"print('hello world')",
            "data/stats.csv": b"id,score\n1,100\n2,95",
            "report.json": b'{"summary": "ok"}',
        }

        manifest = IntegritySealer.create_seal_manifest(session_id, files)
        assert manifest.magic == SEAL_MAGIC_HEADER
        assert manifest.sealed is True
        assert manifest.session_id == session_id
        assert len(manifest.files) == 3
        assert manifest.total_bytes == sum(len(v) for v in files.values())

        json_str = manifest.to_json()
        assert SEAL_MAGIC_HEADER in json_str

        # Verify against matching files
        result = IntegritySealer.verify_manifest_and_files(json_str, files)
        assert result.is_valid is True
        assert result.status == IntegrityStatus.VALID
        assert len(result.corrupted_files) == 0
        assert len(result.missing_files) == 0

    def test_detect_corrupted_file_content(self) -> None:
        session_id = "sess_corrupt"
        files = {
            "code.py": b"import sys",
            "data.bin": b"\x00\x01\x02\x03\x04\x05",
        }

        manifest = IntegritySealer.create_seal_manifest(session_id, files)
        json_str = manifest.to_json()

        # Simulate torn write / bitflip on data.bin
        tampered_files = {
            "code.py": b"import sys",
            "data.bin": b"\x00\x01\x02\x03\x99\x99",  # Modified bytes
        }

        result = IntegritySealer.verify_manifest_and_files(json_str, tampered_files)
        assert result.is_valid is False
        assert result.status == IntegrityStatus.CORRUPTED
        assert "data.bin" in result.corrupted_files
        assert len(result.corrupted_files) == 1

    def test_detect_missing_file(self) -> None:
        session_id = "sess_missing"
        files = {
            "file_a.txt": b"AAA",
            "file_b.txt": b"BBB",
        }

        manifest = IntegritySealer.create_seal_manifest(session_id, files)
        json_str = manifest.to_json()

        # file_b is missing completely (write aborted before uploading file_b)
        incomplete_files = {
            "file_a.txt": b"AAA",
        }

        result = IntegritySealer.verify_manifest_and_files(json_str, incomplete_files)
        assert result.is_valid is False
        assert result.status == IntegrityStatus.CORRUPTED
        assert "file_b.txt" in result.missing_files

    def test_detect_unsealed_manifest(self) -> None:
        session_id = "sess_unsealed"
        files = {"log.txt": b"running..."}

        manifest = IntegritySealer.create_seal_manifest(session_id, files)
        # Force unsealed
        unsealed_manifest = SealManifest(
            magic=manifest.magic,
            version=manifest.version,
            session_id=manifest.session_id,
            sealed=False,
            created_at_epoch_ms=manifest.created_at_epoch_ms,
            files=manifest.files,
            total_bytes=manifest.total_bytes,
            manifest_signature=manifest.manifest_signature,
        )

        result = IntegritySealer.verify_manifest_and_files(unsealed_manifest.to_json(), files)
        assert result.is_valid is False
        assert result.status == IntegrityStatus.UNSEALED
        assert "unsealed" in result.reason.lower()

    def test_detect_tampered_manifest_signature(self) -> None:
        session_id = "sess_sig_tamper"
        files = {"safe.txt": b"content"}

        manifest = IntegritySealer.create_seal_manifest(session_id, files)
        data = json.loads(manifest.to_json())
        data["manifest_signature"] = "invalid_fake_signature"

        result = IntegritySealer.verify_manifest_and_files(json.dumps(data), files)
        assert result.is_valid is False
        assert result.status == IntegrityStatus.CORRUPTED
        assert "signature mismatch" in result.reason.lower()

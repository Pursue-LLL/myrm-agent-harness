"""Unit tests for sealed_io module (atomic write, corruption detection, quarantine)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from myrm_agent_harness.agent.file_snapshot.sealed_io import (
    CURRENT_ENVELOPE_VERSION,
    SealedEnvelope,
    atomic_sealed_write,
    compute_payload_checksum,
    quarantine_corrupted_file,
    verify_and_load_sealed,
)


def test_compute_payload_checksum():
    payload_bytes = b'{"hello": "world"}'
    checksum = compute_payload_checksum(payload_bytes)
    assert checksum.startswith("sha256:")
    assert len(checksum) == 7 + 64


def test_atomic_sealed_write_and_verify(tmp_path: Path):
    target = tmp_path / "session_1" / "msg_1.json"
    data = [{"path": "/workspace/test.txt", "operation": "modify", "timestamp": 123456789}]

    # Atomic write
    written_path = atomic_sealed_write(target, data)
    assert written_path.exists()
    assert written_path == target

    # Read and verify
    is_valid, payload, envelope = verify_and_load_sealed(target)
    assert is_valid is True
    assert payload == data
    assert isinstance(envelope, SealedEnvelope)
    assert envelope.version == CURRENT_ENVELOPE_VERSION
    assert envelope.payload == data
    assert envelope.checksum.startswith("sha256:")


def test_verify_legacy_unsealed_json(tmp_path: Path):
    legacy_file = tmp_path / "legacy.json"
    legacy_data = [{"path": "/workspace/legacy.txt", "operation": "create"}]
    legacy_file.write_text(json.dumps(legacy_data), encoding="utf-8")

    is_valid, payload, envelope = verify_and_load_sealed(legacy_file)
    assert is_valid is True
    assert payload == legacy_data
    assert envelope is None


def test_corruption_detection_checksum_mismatch(tmp_path: Path):
    target = tmp_path / "msg_corrupt.json"
    data = [{"item": 1}]
    atomic_sealed_write(target, data)

    # Tamper with the raw envelope payload without updating checksum
    raw = json.loads(target.read_text("utf-8"))
    raw["payload"] = [{"item": 9999}]
    target.write_text(json.dumps(raw), "utf-8")

    # Verify and load should fail and quarantine
    is_valid, payload, envelope = verify_and_load_sealed(target, auto_quarantine=True)
    assert is_valid is False
    assert payload is None
    assert envelope is None
    assert not target.exists()

    quarantine_dir = tmp_path / ".corrupted"
    assert quarantine_dir.is_dir()
    corrupted_files = list(quarantine_dir.glob("msg_corrupt.json.*.corrupted"))
    assert len(corrupted_files) == 1


def test_corruption_detection_truncated_json(tmp_path: Path):
    target = tmp_path / "msg_truncated.json"
    target.write_text('{"__sealed_envelope__": true, "version": 1, "check', "utf-8")

    is_valid, payload, envelope = verify_and_load_sealed(target, auto_quarantine=True)
    assert is_valid is False
    assert payload is None
    assert not target.exists()

    quarantine_dir = tmp_path / ".corrupted"
    assert quarantine_dir.is_dir()
    corrupted_files = list(quarantine_dir.glob("msg_truncated.json.*.corrupted"))
    assert len(corrupted_files) == 1


def test_quarantine_non_existent_file(tmp_path: Path):
    non_existent = tmp_path / "does_not_exist.json"
    res = quarantine_corrupted_file(non_existent, "reason")
    assert res is None

"""Sealed I/O — Atomic write, SHA-256 corruption detection, and bad-block quarantine.

Provides rock-solid data integrity for persistent snapshots and file state:
- Envelope Contract: SealedEnvelope(version, checksum, sealed_at, payload_bytes, payload)
- 3-Stage Atomic Write: Temp File -> Hardware fsync -> Atomic os.replace
- Corruption Detection: SHA-256 validation against payload serialization
- Quarantine Isolation: Auto-moves corrupt/truncated files to .corrupted/

[POS]
File snapshot subsystem component ensuring zero-corruption persistence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CURRENT_ENVELOPE_VERSION: int = 1
CORRUPTED_DIR_NAME: str = ".corrupted"


class CorruptionError(Exception):
    """Raised when persisted file is corrupted or fails checksum verification."""

    def __init__(self, message: str, file_path: str, reason: str) -> None:
        super().__init__(message)
        self.file_path = file_path
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SealedEnvelope:
    """Immutable envelope wrapping persisted data with integrity metadata."""

    version: int
    checksum: str
    sealed_at: float
    payload_bytes: int
    payload: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "__sealed_envelope__": True,
            "version": self.version,
            "checksum": self.checksum,
            "sealed_at": self.sealed_at,
            "payload_bytes": self.payload_bytes,
            "payload": self.payload,
        }


def compute_payload_checksum(payload_bytes: bytes) -> str:
    """Compute standard SHA-256 checksum with prefix."""
    digest = hashlib.sha256(payload_bytes).hexdigest()
    return f"sha256:{digest}"


def quarantine_corrupted_file(file_path: Path, reason: str) -> Path | None:
    """Move corrupted file to adjacent .corrupted/ quarantine folder."""
    try:
        if not file_path.exists() or not file_path.is_file():
            return None

        quarantine_dir = file_path.parent / CORRUPTED_DIR_NAME
        quarantine_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time() * 1000)
        target = quarantine_dir / f"{file_path.name}.{timestamp}.corrupted"
        shutil.move(str(file_path), str(target))

        logger.warning(
            "Persisted file '%s' corrupted (%s); quarantined to '%s'",
            file_path,
            reason,
            target,
        )
        return target
    except OSError as err:
        logger.error("Failed to quarantine corrupted file '%s': %s", file_path, err)
        return None


def atomic_sealed_write(
    target_path: str | Path,
    payload: Any,
    ensure_ascii: bool = False,
) -> Path:
    """Atomically write data wrapped in a sealed integrity envelope.

    1. Encodes payload to canonical JSON bytes and computes SHA-256.
    2. Constructs SealedEnvelope.
    3. Writes to unique .tmp file in target directory.
    4. Calls os.fsync to force physical flush to storage.
    5. Atomically replaces target file using os.replace.
    """
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # 1. Encode payload and compute checksum
    payload_raw_bytes = json.dumps(payload, ensure_ascii=ensure_ascii, sort_keys=True).encode("utf-8")
    checksum = compute_payload_checksum(payload_raw_bytes)

    envelope = SealedEnvelope(
        version=CURRENT_ENVELOPE_VERSION,
        checksum=checksum,
        sealed_at=time.time(),
        payload_bytes=len(payload_raw_bytes),
        payload=payload,
    )
    envelope_data = json.dumps(envelope.to_dict(), ensure_ascii=ensure_ascii, indent=2)

    # 2. Atomic 3-stage write
    tmp_path = target.parent / f".tmp.{uuid.uuid4().hex}.sealed"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(envelope_data)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, target)
        return target
    except BaseException:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def verify_and_load_sealed(
    target_path: str | Path,
    auto_quarantine: bool = True,
) -> tuple[bool, Any, SealedEnvelope | None]:
    """Load and verify a sealed file.

    Returns:
        (is_valid, payload, envelope)

    If file is corrupt and auto_quarantine=True, moves it to .corrupted/.
    """
    target = Path(target_path)
    if not target.is_file():
        return False, None, None

    try:
        raw_text = target.read_text("utf-8")
        if not raw_text.strip():
            raise CorruptionError("Empty file content", str(target), "empty_file")

        data = json.loads(raw_text)
        if not isinstance(data, dict) or not data.get("__sealed_envelope__"):
            # Backward-compatible fallback for legacy plain JSON lists/dicts
            return True, data, None

        version = data.get("version", 1)
        checksum = data.get("checksum", "")
        sealed_at = data.get("sealed_at", 0.0)
        payload_bytes_len = data.get("payload_bytes", 0)
        payload = data.get("payload")

        # Verify payload integrity
        expected_raw_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        actual_checksum = compute_payload_checksum(expected_raw_bytes)

        if actual_checksum != checksum:
            raise CorruptionError(
                f"Checksum mismatch: expected {checksum}, got {actual_checksum}",
                str(target),
                "checksum_mismatch",
            )

        envelope = SealedEnvelope(
            version=version,
            checksum=checksum,
            sealed_at=sealed_at,
            payload_bytes=payload_bytes_len,
            payload=payload,
        )
        return True, payload, envelope

    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, CorruptionError) as err:
        reason = getattr(err, "reason", type(err).__name__)
        logger.warning("Sealed file corruption detected for '%s': %s", target, err)
        if auto_quarantine:
            quarantine_corrupted_file(target, reason)
        return False, None, None
    except OSError as err:
        logger.error("I/O error reading sealed file '%s': %s", target, err)
        return False, None, None

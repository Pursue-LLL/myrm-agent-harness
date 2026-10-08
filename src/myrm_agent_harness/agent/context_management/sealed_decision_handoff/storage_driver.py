# [INPUT] SealedReceipt, bytes ciphertext
# [OUTPUT] DecisionStorageDriver, SandboxVolumeDecisionStorageDriver, PointerChainEntry
# [POS] Storage driver protocol and sandbox volume persistence with immutable pointer chains

"""Storage driver abstraction and sandbox volume persistence for sealed decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Protocol

from myrm_agent_harness.agent.context_management.sealed_decision_handoff.sealed_decision_types import (
    SealedDecisionError,
    SealedReceipt,
)


@dataclass(frozen=True)
class PointerChainEntry:
    """Immutable pointer record in a topic's version chain."""

    receipt_id: str
    topic: str
    sha256_digest: str
    created_at_iso: str
    version: int


class DecisionStorageDriver(Protocol):
    """Protocol for sovereign sealed decision persistence backends."""

    def store_sealed_package(
        self,
        receipt: SealedReceipt,
        ciphertext: bytes,
    ) -> str:
        """Store ciphertext and receipt, returning canonical receipt ID."""
        ...

    def fetch_sealed_package(
        self,
        receipt_id: str,
    ) -> tuple[SealedReceipt, bytes]:
        """Retrieve receipt and ciphertext by identifier."""
        ...

    def list_receipts(
        self,
        topic: str | None = None,
    ) -> list[SealedReceipt]:
        """List available receipts, optionally filtering by topic."""
        ...


class SandboxVolumeDecisionStorageDriver:
    """Persistent storage driver backed by sandbox volume with 0600 permissions."""

    def __init__(self, volume_dir: str | Path) -> None:
        self._volume_path = Path(volume_dir).resolve()
        self._volume_path.mkdir(parents=True, exist_ok=True)
        try:
            self._volume_path.chmod(0o700)
        except OSError:
            pass  # Non-POSIX or restricted sandbox fallback

    @staticmethod
    def _topic_slug(topic: str) -> str:
        """Sanitize topic name into a safe file slug."""
        return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in topic)

    def _get_chain_path(self, topic: str) -> Path:
        slug = self._topic_slug(topic)
        return self._volume_path / f"pointer_chain_{slug}.json"

    def store_sealed_package(
        self,
        receipt: SealedReceipt,
        ciphertext: bytes,
    ) -> str:
        """Store ciphertext and receipt with atomic writes and immutable pointer chaining."""
        receipt_file = self._volume_path / f"{receipt.receipt_id}.receipt.json"
        sealed_file = self._volume_path / f"{receipt.receipt_id}.sealed"

        # 1. Write sealed ciphertext securely (0600)
        sealed_tmp = self._volume_path / f"{receipt.receipt_id}.sealed.tmp"
        with open(sealed_tmp, "wb") as f:
            f.write(ciphertext)
            f.flush()
            os.fsync(f.fileno())

        try:
            sealed_tmp.chmod(0o600)
        except OSError:
            pass
        sealed_tmp.replace(sealed_file)

        # 2. Write receipt JSON securely
        receipt_tmp = self._volume_path / f"{receipt.receipt_id}.receipt.json.tmp"
        with open(receipt_tmp, "w", encoding="utf-8") as f:
            json.dump(receipt.to_dict(), f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        try:
            receipt_tmp.chmod(0o600)
        except OSError:
            pass
        receipt_tmp.replace(receipt_file)

        # 3. Update immutable pointer chain for topic
        self._append_pointer(receipt)
        return receipt.receipt_id

    def fetch_sealed_package(
        self,
        receipt_id: str,
    ) -> tuple[SealedReceipt, bytes]:
        """Retrieve receipt metadata and sealed ciphertext bytes."""
        receipt_file = self._volume_path / f"{receipt_id}.receipt.json"
        sealed_file = self._volume_path / f"{receipt_id}.sealed"

        if not receipt_file.exists():
            raise SealedDecisionError(
                f"Receipt '{receipt_id}' not found on storage volume"
            )
        if not sealed_file.exists():
            raise SealedDecisionError(
                f"Sealed ciphertext '{receipt_id}' not found on storage volume"
            )

        with open(receipt_file, "r", encoding="utf-8") as f:
            raw_receipt = json.load(f)
        receipt = SealedReceipt.from_dict(raw_receipt)

        with open(sealed_file, "rb") as f:
            ciphertext = f.read()

        return receipt, ciphertext

    def list_receipts(
        self,
        topic: str | None = None,
    ) -> list[SealedReceipt]:
        """List all stored receipts, optionally filtered by matching topic."""
        results: list[SealedReceipt] = []
        for receipt_file in self._volume_path.glob("*.receipt.json"):
            try:
                with open(receipt_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                receipt = SealedReceipt.from_dict(data)
                if topic is None or receipt.topic == topic:
                    results.append(receipt)
            except Exception:
                continue

        # Sort descending by created_at_iso
        results.sort(key=lambda r: r.created_at_iso, reverse=True)
        return results

    def get_latest_receipt(self, topic: str) -> SealedReceipt | None:
        """Fetch the latest receipt for a topic using the immutable pointer chain."""
        chain_path = self._get_chain_path(topic)
        if not chain_path.exists():
            receipts = self.list_receipts(topic=topic)
            return receipts[0] if receipts else None

        try:
            with open(chain_path, "r", encoding="utf-8") as f:
                chain = json.load(f)
            if not chain:
                return None
            latest_entry = chain[-1]
            receipt, _ = self.fetch_sealed_package(latest_entry["receipt_id"])
            return receipt
        except Exception:
            return None

    def _append_pointer(self, receipt: SealedReceipt) -> None:
        """Append a newly sealed receipt to the immutable version chain."""
        chain_path = self._get_chain_path(receipt.topic)
        chain: list[dict[str, str | int]] = []

        if chain_path.exists():
            try:
                with open(chain_path, "r", encoding="utf-8") as f:
                    chain = json.load(f)
            except Exception:
                chain = []

        version = len(chain) + 1
        entry = PointerChainEntry(
            receipt_id=receipt.receipt_id,
            topic=receipt.topic,
            sha256_digest=receipt.sha256_digest,
            created_at_iso=receipt.created_at_iso,
            version=version,
        )
        chain.append(asdict(entry))

        tmp_path = chain_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(chain, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        try:
            tmp_path.chmod(0o600)
        except OSError:
            pass
        tmp_path.replace(chain_path)

"""Invisible provenance watermark injection and extraction engine (Item 159).

[INPUT]
- Plaintext memory texts, ProvenanceWatermark payloads, and watermarked documents.

[OUTPUT]
- Watermarked texts embedded with zero-width symbols and decoded ProvenanceWatermark tokens.

[POS]
- Invisible watermark engine in myrm_agent_harness/toolkits/memory/zk_vault_watermark/.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .models import ProvenanceWatermark

ZERO_WIDTH_ZERO = "\u200B"  # Bit 0: Zero-Width Space
ZERO_WIDTH_ONE = "\u200C"   # Bit 1: Zero-Width Non-Joiner
ZERO_WIDTH_FRAME = "\u200D" # Frame Sentinel: Zero-Width Joiner


class InvisibleWatermarkEngine:
    """Injects and decodes invisible zero-width provenance watermarks for context leakage traceability."""

    @staticmethod
    def _compute_signature(tenant_id: str, user_id: str, timestamp_iso: str) -> str:
        """Calculate monotonic integrity signature for the watermark payload."""
        payload = f"{tenant_id}|{user_id}|{timestamp_iso}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]

    @classmethod
    def _encode_to_zero_width(cls, raw_str: str) -> str:
        """Convert UTF-8 string into a binary zero-width sequence delimited by sentinels."""
        data_bytes = raw_str.encode("utf-8")
        bit_chars: list[str] = []
        for b in data_bytes:
            bits = f"{b:08b}"
            for bit in bits:
                bit_chars.append(ZERO_WIDTH_ONE if bit == "1" else ZERO_WIDTH_ZERO)

        encoded_bits = "".join(bit_chars)
        return f"{ZERO_WIDTH_FRAME}{encoded_bits}{ZERO_WIDTH_FRAME}"

    @classmethod
    def _decode_from_zero_width(cls, zero_width_seq: str) -> str | None:
        """Decode binary zero-width sequence back into UTF-8 string."""
        if not (
            zero_width_seq.startswith(ZERO_WIDTH_FRAME)
            and zero_width_seq.endswith(ZERO_WIDTH_FRAME)
        ):
            return None

        inner = zero_width_seq[1:-1]
        if len(inner) % 8 != 0:
            return None

        byte_list: list[int] = []
        for i in range(0, len(inner), 8):
            chunk = inner[i : i + 8]
            bit_str = "".join("1" if ch == ZERO_WIDTH_ONE else "0" for ch in chunk)
            byte_list.append(int(bit_str, 2))

        try:
            return bytes(byte_list).decode("utf-8")
        except UnicodeDecodeError:
            return None

    def embed_watermark(
        self,
        text: str,
        tenant_id: str,
        user_id: str,
        timestamp_iso: str | None = None,
    ) -> tuple[str, ProvenanceWatermark]:
        """Inject invisible provenance watermark into exported memory content."""
        ts_str = timestamp_iso or datetime.now(timezone.utc).isoformat()
        signature = self._compute_signature(tenant_id, user_id, ts_str)
        watermark = ProvenanceWatermark(
            tenant_id=tenant_id,
            user_id=user_id,
            timestamp_iso=ts_str,
            signature=signature,
        )

        encoded_payload = f"{tenant_id}::{user_id}::{ts_str}::{signature}"
        zw_token = self._encode_to_zero_width(encoded_payload)

        # Inject after the first sentence or newline, or at start if empty
        if "\n" in text:
            parts = text.split("\n", 1)
            watermarked_text = f"{parts[0]}{zw_token}\n{parts[1]}"
        elif ". " in text:
            parts = text.split(". ", 1)
            watermarked_text = f"{parts[0]}.{zw_token} {parts[1]}"
        else:
            watermarked_text = f"{zw_token}{text}"

        return watermarked_text, watermark

    def extract_watermark(self, text: str) -> ProvenanceWatermark | None:
        """Scan text and decode embedded invisible zero-width watermark."""
        # Find frame boundaries
        start_idx = text.find(ZERO_WIDTH_FRAME)
        if start_idx == -1:
            return None

        end_idx = text.find(ZERO_WIDTH_FRAME, start_idx + 1)
        if end_idx == -1:
            return None

        zw_seq = text[start_idx : end_idx + 1]
        decoded_payload = self._decode_from_zero_width(zw_seq)
        if not decoded_payload or "::" not in decoded_payload:
            return None

        parts = decoded_payload.split("::")
        if len(parts) != 4:
            return None

        tenant_id, user_id, ts_str, signature = parts
        expected_sig = self._compute_signature(tenant_id, user_id, ts_str)
        if signature != expected_sig:
            return None

        return ProvenanceWatermark(
            tenant_id=tenant_id,
            user_id=user_id,
            timestamp_iso=ts_str,
            signature=signature,
        )

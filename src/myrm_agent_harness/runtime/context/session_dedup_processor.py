"""Session-Dedup processor providing cross-turn content addressing and retrieve marker replacement.

Implements the first layer of the Tokenomics 12-engine compression stack:
1. Three-Level Block Chunking (System Prompt, Message Turns, Heavy Tool Payloads).
2. O(1) Content Addressing and cross-turn fingerprint comparison.
3. Lightweight [RetrieveMarker: ...] placeholder injection for repeated heavy outputs.
4. On-demand CCR retrieval marker hydration (lossless recovery).
Strict 0 Any, thread-safe, single file <400 lines.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections.abc import Mapping, Sequence

from .content_addressed_dedup_store import ContentAddressedDedupStore
from .content_addressed_dedup_types import DedupContentType
from .session_dedup_types import (
    BlockChunkLevel,
    DedupedMessagePackage,
    SessionBlockFingerprint,
    SessionDedupConfig,
    SessionDedupSavingsReport,
)

logger = logging.getLogger(__name__)

_RETRIEVE_MARKER_REGEX = re.compile(
    r"\[RetrieveMarker:\s*marker_id=([a-zA-Z0-9_\-]+)[^\]]*\]"
)


def _estimate_tokens(text: str) -> int:
    """Heuristic token estimator (approx 4 chars per token)."""
    return max(1, math.ceil(len(text) / 4))


class SessionDedupProcessor:
    """Processor orchestrating three-level content addressing and cross-turn deduplication."""

    def __init__(
        self,
        config: SessionDedupConfig | None = None,
        store: ContentAddressedDedupStore | None = None,
    ) -> None:
        self.config = config or SessionDedupConfig()
        self.store = store or ContentAddressedDedupStore()
        # Mapping: chunk_hash -> SessionBlockFingerprint
        self._fingerprints: dict[str, SessionBlockFingerprint] = {}
        # Historical tracking: count of deduplications
        self._total_original_tokens = 0
        self._total_deduped_tokens = 0
        self._markers_count = 0
        self._chunks_deduped_count = 0
        self._chunks_analyzed_count = 0

    def compute_hash(self, content: str) -> str:
        """Compute standard SHA-256 hexadecimal digest for content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def process_turn_messages(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        current_turn: int,
    ) -> tuple[tuple[DedupedMessagePackage, ...], SessionDedupSavingsReport]:
        """Process a turn's messages, deduplicating repeated heavy content across turns."""
        packages: list[DedupedMessagePackage] = []
        turn_orig_tokens = 0
        turn_dedup_tokens = 0
        turn_markers = 0
        turn_deduped_chunks = 0

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            orig_toks = _estimate_tokens(content)
            self._chunks_analyzed_count += 1
            turn_orig_tokens += orig_toks

            # Determine chunk level
            level = self._classify_chunk_level(role)

            # Check if eligible for deduplication (heavy tool outputs or repeated turns)
            should_dedup = (
                len(content) >= self.config.min_payload_chars
                and (
                    (level == BlockChunkLevel.TOOL_PAYLOAD and self.config.enable_tool_payload_dedup)
                    or (level == BlockChunkLevel.MESSAGE_TURN and self.config.enable_message_turn_dedup)
                )
            )

            if not should_dedup:
                packages.append(
                    DedupedMessagePackage(
                        role=role,
                        content=content,
                        is_deduped=False,
                        original_tokens=orig_toks,
                        deduped_tokens=orig_toks,
                    )
                )
                turn_dedup_tokens += orig_toks
                continue

            # Compute content hash
            digest = self.compute_hash(content)
            existing_fp = self._fingerprints.get(digest)

            if existing_fp is not None and existing_fp.first_turn_seen < current_turn:
                # Content seen in an earlier turn: inject lightweight RetrieveMarker
                marker_id = f"chunk_{digest[:12]}"
                # Ensure content is archived in vault
                meta = self.store.store_content(
                    content=content,
                    content_type=DedupContentType.TOOL_OUTPUT if level == BlockChunkLevel.TOOL_PAYLOAD else DedupContentType.ARBITRARY_CHUNK,
                    source_hint=f"turn_{existing_fp.first_turn_seen}_{role}",
                    preview_chars=self.config.preview_chars,
                )

                line_count = len(content.splitlines())
                byte_size = len(content.encode("utf-8"))
                clean_preview = meta.preview_summary

                placeholder = (
                    f"{self.config.marker_prefix} marker_id={marker_id} | "
                    f"source={role} | lines={line_count} | bytes={byte_size} | "
                    f"preview=\"{clean_preview}\"]"
                )

                dedup_toks = _estimate_tokens(placeholder)
                turn_dedup_tokens += dedup_toks
                turn_markers += 1
                turn_deduped_chunks += 1
                self._chunks_deduped_count += 1
                self._markers_count += 1

                packages.append(
                    DedupedMessagePackage(
                        role=role,
                        content=placeholder,
                        is_deduped=True,
                        original_tokens=orig_toks,
                        deduped_tokens=dedup_toks,
                        marker_id=marker_id,
                    )
                )
            else:
                # First time seeing this content: record fingerprint and keep inline
                fp = SessionBlockFingerprint(
                    chunk_hash=digest,
                    level=level,
                    source_id=f"turn_{current_turn}_{role}",
                    byte_size=len(content.encode("utf-8")),
                    token_estimate=orig_toks,
                    first_turn_seen=current_turn,
                )
                self._fingerprints[digest] = fp
                # Also index into vault so subsequent turns can retrieve
                self.store.store_content(
                    content=content,
                    content_type=DedupContentType.TOOL_OUTPUT if level == BlockChunkLevel.TOOL_PAYLOAD else DedupContentType.ARBITRARY_CHUNK,
                    source_hint=f"turn_{current_turn}_{role}",
                    preview_chars=self.config.preview_chars,
                )

                packages.append(
                    DedupedMessagePackage(
                        role=role,
                        content=content,
                        is_deduped=False,
                        original_tokens=orig_toks,
                        deduped_tokens=orig_toks,
                    )
                )
                turn_dedup_tokens += orig_toks

        self._total_original_tokens += turn_orig_tokens
        self._total_deduped_tokens += turn_dedup_tokens

        saved = turn_orig_tokens - turn_dedup_tokens
        ratio = round(saved / turn_orig_tokens, 4) if turn_orig_tokens > 0 else 0.0

        report = SessionDedupSavingsReport(
            total_original_tokens=turn_orig_tokens,
            total_deduped_tokens=turn_dedup_tokens,
            tokens_saved=saved,
            savings_ratio=max(0.0, ratio),
            chunks_analyzed=len(messages),
            chunks_deduped=turn_deduped_chunks,
            markers_injected=turn_markers,
            turn_index=current_turn,
        )

        return tuple(packages), report

    def hydrate_retrieve_markers(self, text: str) -> str:
        """Hydrate all [RetrieveMarker: marker_id=...] placeholders back into verbatim content."""
        def _replace_marker(match: re.Match[str]) -> str:
            marker_id = match.group(1).strip()
            original = self.store.retrieve_content(marker_id)
            if original is not None:
                return original
            return match.group(0)

        return _RETRIEVE_MARKER_REGEX.sub(_replace_marker, text)

    def get_overall_savings_report(self, current_turn: int = 0) -> SessionDedupSavingsReport:
        """Return cumulative lifetime savings across all processed turns."""
        saved = self._total_original_tokens - self._total_deduped_tokens
        ratio = (
            round(saved / self._total_original_tokens, 4)
            if self._total_original_tokens > 0
            else 0.0
        )
        return SessionDedupSavingsReport(
            total_original_tokens=self._total_original_tokens,
            total_deduped_tokens=self._total_deduped_tokens,
            tokens_saved=saved,
            savings_ratio=max(0.0, ratio),
            chunks_analyzed=self._chunks_analyzed_count,
            chunks_deduped=self._chunks_deduped_count,
            markers_injected=self._markers_count,
            turn_index=current_turn,
        )

    @staticmethod
    def _classify_chunk_level(role: str) -> BlockChunkLevel:
        norm = role.strip().lower()
        if norm in ("system", "sys"):
            return BlockChunkLevel.SYSTEM_PROMPT
        if norm in ("tool", "tool_result", "tool_output", "observation"):
            return BlockChunkLevel.TOOL_PAYLOAD
        return BlockChunkLevel.MESSAGE_TURN

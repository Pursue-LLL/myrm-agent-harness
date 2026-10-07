"""CCR (Chunk-Cache Retrieval) Context Archival Transformer.

Transforms bulky context blocks into lightweight retrieve markers and deduplicates
repeated files and tool outputs across conversational turns.

[INPUT]
- runtime.context.content_addressed_dedup_store::ContentAddressedDedupStore (POS: Content-addressed chunk
  storage and session turn deduplication store.)
- runtime.context.content_addressed_dedup_types::CCRTransformResult, DedupConfig, DedupContentType (POS:
  Strongly typed data contracts for Content-Addressed Session Dedup and CCR Context Archival.)

[OUTPUT]
- CCRContextArchivalTransformer: Transforms raw context payloads into token-efficient references and CCR
  markers.

[POS]
CCR (Chunk-Cache Retrieval) Context Archival Transformer.
"""

from __future__ import annotations

import re

from myrm_agent_harness.runtime.context.content_addressed_dedup_store import (
    ContentAddressedDedupStore,
)
from myrm_agent_harness.runtime.context.content_addressed_dedup_types import (
    CCRTransformResult,
    DedupConfig,
    DedupContentType,
)


class CCRContextArchivalTransformer:
    """Transforms raw context payloads into token-efficient references and CCR markers."""

    def __init__(
        self,
        store: ContentAddressedDedupStore | None = None,
        config: DedupConfig | None = None,
    ) -> None:
        self.store = store or ContentAddressedDedupStore()
        self.config = config or DedupConfig()

    def retrieve_artifact(self, marker_id_or_hash: str) -> str:
        """On-demand retrieval tool callable by the agent or harness."""
        content = self.store.retrieve_content(marker_id_or_hash)
        if content is None:
            return f"[Error: Archival chunk '{marker_id_or_hash}' not found in dedup store.]"
        return content

    def transform_turn_content(
        self,
        content: str,
        current_turn: int,
        source_hint: str = "general_output",
        content_type: DedupContentType = DedupContentType.TOOL_OUTPUT,
    ) -> CCRTransformResult:
        """Process content for a specific conversational turn.

        Checks for cross-turn repetition first (Session-Dedup).
        If not repeated but exceeds line/char boundaries, converts to a CCR Retrieve Marker.
        """
        orig_len = len(content)
        line_count = len(content.splitlines())

        # 1. Check for cross-turn verbatim deduplication (Session-Dedup)
        if len(content.strip()) >= self.config.min_dedup_chars:
            is_repeated, anchor = self.store.track_session_turn(
                turn_index=current_turn,
                source_hint=source_hint,
                content=content,
            )
            if is_repeated and anchor is not None:
                rendered = anchor.format_ref_directive()
                comp_len = len(rendered)
                ratio = round((orig_len - comp_len) / orig_len, 4) if orig_len > 0 else 0.0
                return CCRTransformResult(
                    transformed_content=rendered,
                    archived_count=0,
                    deduped_count=1,
                    original_chars=orig_len,
                    compressed_chars=comp_len,
                    reduction_ratio=max(0.0, ratio),
                    refs_created=(anchor,),
                )

        # 2. Check if content is oversized and warrants CCR archival
        if line_count > self.config.max_inline_lines or orig_len > (self.config.min_dedup_chars * 10):
            meta = self.store.store_content(
                content=content,
                content_type=content_type,
                source_hint=source_hint,
                preview_chars=self.config.preview_chars,
            )
            rendered_marker = meta.format_marker_directive()
            comp_len = len(rendered_marker)
            ratio = round((orig_len - comp_len) / orig_len, 4) if orig_len > 0 else 0.0
            return CCRTransformResult(
                transformed_content=rendered_marker,
                archived_count=1,
                deduped_count=0,
                original_chars=orig_len,
                compressed_chars=comp_len,
                reduction_ratio=max(0.0, ratio),
                markers_created=(meta,),
            )

        # 3. Content within acceptable bounds; keep inline as-is
        return CCRTransformResult(
            transformed_content=content,
            archived_count=0,
            deduped_count=0,
            original_chars=orig_len,
            compressed_chars=orig_len,
            reduction_ratio=0.0,
        )

    def expand_retrieve_markers(self, text: str) -> str:
        """Utility to expand all retrieve markers back into verbatim text (for debugging/replay)."""
        marker_pattern = re.compile(
            r"\[Retrieve-Marker:\s*marker_id=([a-zA-Z0-9_-]+)[^\]]*\]"
        )

        def replace_with_original(match: re.Match[str]) -> str:
            m_id = match.group(1)
            original = self.store.retrieve_content(m_id)
            return original if original is not None else match.group(0)

        return marker_pattern.sub(replace_with_original, text)

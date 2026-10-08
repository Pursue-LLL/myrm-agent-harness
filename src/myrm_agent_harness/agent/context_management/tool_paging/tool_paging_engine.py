"""Engine for Model-Native dynamic tool pruning and context paging offload.

Provides tier-aware tool schema compacting, automatic large output stubbing
to virtual page table blob stores, and on-demand line-sliced paging (page-in).

[INPUT]
- agent.context_management.tool_paging.tool_paging_types::ModelTier, PageInSlice, ToolBlobRecord,
  ToolOutputStub, ToolPagingConfig, ToolSchemaDefinition (POS: Types and schemas for Model-Native tool pruning
  and context paging offload suite.)

[OUTPUT]
- ModelNativeToolPagingEngine: Core engine governing tool pruning and virtual paging for large execution
  outputs.

[POS]
Engine for Model-Native dynamic tool pruning and context paging offload.
"""

import logging
import re
from typing import Optional

from .tool_paging_types import (
    ModelTier,
    PageInSlice,
    ToolBlobRecord,
    ToolOutputStub,
    ToolPagingConfig,
    ToolSchemaDefinition,
)

logger = logging.getLogger(__name__)


class ModelNativeToolPagingEngine:
    """Core engine governing tool pruning and virtual paging for large execution outputs."""

    def __init__(self, config: Optional[ToolPagingConfig] = None) -> None:
        self.config = config or ToolPagingConfig()
        self._session_blobs: dict[str, dict[str, ToolBlobRecord]] = {}

    def compact_tool_schemas_for_tier(
        self,
        tools: list[ToolSchemaDefinition],
        tier: ModelTier,
    ) -> list[dict[str, str]]:
        """Compact and prune tool schemas tailored to the target model tier."""
        return [tool.to_schema_for_tier(tier) for tool in tools]

    def extract_output_summary(self, tool_name: str, raw_output: str) -> str:
        """Extract a high-salience 1-line diagnostic summary from output text."""
        lines = raw_output.splitlines()
        total_lines = len(lines)
        if total_lines == 0:
            return "Empty output."

        # Search for error or status indicators
        error_matches = [line.strip() for line in lines if re.search(r"(error|failed|fatal|exception|fail)", line, re.IGNORECASE)]
        if error_matches:
            first_err = error_matches[0][:100]
            return f"Found {len(error_matches)} errors in {total_lines} lines. First: '{first_err}'"

        # Check for success indicators
        success_matches = [line.strip() for line in lines if re.search(r"(success|passed|ok|completed|build successful)", line, re.IGNORECASE)]
        if success_matches:
            return f"Execution succeeded with {total_lines} lines of output."

        return f"Completed with {total_lines} lines of text."

    def process_tool_output(
        self,
        session_id: str,
        tool_name: str,
        raw_output: str,
    ) -> tuple[str, bool, Optional[ToolBlobRecord]]:
        """Evaluate output size; offload to blob store if exceeding threshold, else pass through.

        Returns (effective_text_for_context, is_offloaded, blob_record).
        """
        byte_size = len(raw_output.encode("utf-8"))
        if byte_size <= self.config.offload_byte_threshold:
            return raw_output, False, None

        # Build summary and preview
        summary = self.extract_output_summary(tool_name, raw_output)
        record = ToolBlobRecord.create(tool_name=tool_name, raw_content=raw_output, summary=summary)

        # Store in session virtual page table
        if session_id not in self._session_blobs:
            self._session_blobs[session_id] = {}
        self._session_blobs[session_id][record.blob_id] = record

        # Generate head preview
        lines = raw_output.splitlines()
        preview_lines = lines[: self.config.preview_line_count]
        preview_head = "\n".join(preview_lines)

        stub = ToolOutputStub(
            blob_id=record.blob_id,
            tool_name=tool_name,
            byte_size=byte_size,
            line_count=len(lines),
            summary=summary,
            preview_head=preview_head,
            ref_uri=f"blob://{record.blob_id}",
        )

        card_text = stub.format_card()
        logger.info(
            "Offloaded tool output for %s: %d bytes -> %s (%d lines)",
            tool_name,
            byte_size,
            record.blob_id,
            len(lines),
        )
        return card_text, True, record

    def page_in(
        self,
        session_id: str,
        blob_id: str,
        start_line: int,
        end_line: int,
    ) -> PageInSlice:
        """Retrieve bounded line slice from offloaded blob without loading entire document."""
        session_table = self._session_blobs.get(session_id, {})
        record = session_table.get(blob_id)
        if not record:
            raise KeyError(f"Blob {blob_id} not found in session {session_id} virtual page table")

        lines = record.content.splitlines()
        total_lines = len(lines)

        # 1-indexed line clamping
        clamped_start = max(1, start_line)
        clamped_end = min(total_lines, max(clamped_start, end_line))

        # Enforce max page window constraint
        if clamped_end - clamped_start + 1 > self.config.max_page_lines:
            clamped_end = clamped_start + self.config.max_page_lines - 1

        selected_lines = lines[clamped_start - 1 : clamped_end]
        content_slice = "\n".join(selected_lines)

        return PageInSlice(
            blob_id=blob_id,
            start_line=clamped_start,
            end_line=clamped_end,
            total_lines=total_lines,
            content_slice=content_slice,
            lines_returned=len(selected_lines),
        )

    def get_blob(self, session_id: str, blob_id: str) -> Optional[ToolBlobRecord]:
        """Fetch full record from virtual page table if present."""
        return self._session_blobs.get(session_id, {}).get(blob_id)

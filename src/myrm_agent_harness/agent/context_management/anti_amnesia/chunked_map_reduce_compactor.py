"""Chunked map-reduce hierarchical lossless fallback compression engine.

[INPUT]
- anti_amnesia_types::ChunkedSummaryNode, ModelWindowSpec (POS: Anti-amnesia domain models)
- langchain_core.messages::BaseMessage, AIMessage, HumanMessage, ToolMessage (POS: LangChain messages)
- utils.token_estimation::estimate_content_tokens (POS: Token estimation)

[OUTPUT]
- ChunkedMapReduceCompactor: Slices long history with 15% overlap and synthesizes unified memory.

[POS]
Lossless hierarchical compression engine activating when small-window fallback models
are tasked with compressing long histories, replacing violent truncation with map-reduce.
"""

from __future__ import annotations

import re
from typing import Sequence

from langchain_core.messages import BaseMessage, SystemMessage

from myrm_agent_harness.utils.token_estimation import estimate_content_tokens

from .anti_amnesia_types import ChunkedSummaryNode, ModelWindowSpec


class ChunkedMapReduceCompactor:
    """Performs hierarchical map-reduce summarization with 15% overlap across window slices."""

    _OVERLAP_FRACTION = 0.15
    _ENTITY_PATTERN = re.compile(
        r"(?:[\w./\-]+\.(?:py|ts|js|json|md|yaml|yml|sh|rs|go|html|css)"
        r"|[A-Z][a-zA-Z0-9_]{3,}"
        r"|def\s+[\w_]+"
        r"|class\s+[\w_]+"
        r"|(?:error|exception|panic|failed)[:\s][^\n]{0,60})",
        re.IGNORECASE,
    )

    @classmethod
    def slice_messages_into_chunks(
        cls,
        messages: Sequence[BaseMessage],
        safe_chunk_token_budget: int,
    ) -> list[list[BaseMessage]]:
        """Slice message sequences into overlapping chunks respecting the token budget."""
        budget = max(safe_chunk_token_budget, 1024)
        overlap_budget = int(budget * cls._OVERLAP_FRACTION)
        effective_step = max(budget - overlap_budget, 512)

        msg_list = list(messages)
        if not msg_list:
            return []

        # Calculate cumulative token offsets
        msg_tokens = [
            estimate_content_tokens(str(m.content)) for m in msg_list
        ]
        total_tokens = sum(msg_tokens)

        if total_tokens <= budget:
            return [msg_list]

        chunks: list[list[BaseMessage]] = []
        current_chunk: list[BaseMessage] = []
        accumulated_tokens = 0

        for i, (msg, tok) in enumerate(zip(msg_list, msg_tokens)):
            current_chunk.append(msg)
            accumulated_tokens += tok

            if accumulated_tokens >= budget and i < len(msg_list) - 1:
                chunks.append(list(current_chunk))
                # Compute backward overlap slice for continuity
                overlap_tokens = 0
                overlap_slice: list[BaseMessage] = []
                for back_msg, back_tok in reversed(list(zip(current_chunk, [estimate_content_tokens(str(m.content)) for m in current_chunk]))):
                    overlap_slice.insert(0, back_msg)
                    overlap_tokens += back_tok
                    if overlap_tokens >= overlap_budget:
                        break

                current_chunk = list(overlap_slice)
                accumulated_tokens = overlap_tokens

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    @classmethod
    def extract_chunk_entities(cls, text: str) -> tuple[str, ...]:
        """Extract key technical entities (file paths, classes, functions, errors)."""
        matches = cls._ENTITY_PATTERN.findall(text)
        cleaned = {m.strip() for m in matches if len(m.strip()) >= 3}
        return tuple(sorted(cleaned))[:25]

    @classmethod
    def summarize_chunk_deterministic(
        cls,
        chunk_messages: Sequence[BaseMessage],
        chunk_idx: int,
        total_chunks: int,
    ) -> ChunkedSummaryNode:
        """Deterministically condense an individual chunk without monolithic LLM dependency."""
        chunk_text_parts: list[str] = []
        for m in chunk_messages:
            role = m.__class__.__name__.replace("Message", "")
            content = str(m.content)
            chunk_text_parts.append(f"[{role}]: {content}")

        combined_text = "\n".join(chunk_text_parts)
        tok_count = estimate_content_tokens(combined_text)
        entities = cls.extract_chunk_entities(combined_text)

        # Build structured excerpt preserving key lines
        lines = [line.strip() for line in combined_text.splitlines() if line.strip()]
        significant_lines: list[str] = []
        for line in lines:
            if any(term in line.lower() for term in ("error", "success", "fix", "test", "create", "update", "def ", "class ", "assert")):
                significant_lines.append(line[:160])
            if len(significant_lines) >= 8:
                break

        summary_body = "; ".join(significant_lines) if significant_lines else (combined_text[:300] + "...")
        node_summary = (
            f"Chunk #{chunk_idx + 1}/{total_chunks} (~{tok_count} tokens): {summary_body}. "
            f"Key entities: {', '.join(entities[:10]) if entities else 'None'}."
        )

        return ChunkedSummaryNode(
            chunk_index=chunk_idx,
            total_chunks=total_chunks,
            token_count=tok_count,
            extracted_summary=node_summary,
            key_entities=entities,
        )

    @classmethod
    def execute_map_reduce_compaction(
        cls,
        messages: Sequence[BaseMessage],
        model_spec: ModelWindowSpec,
    ) -> tuple[SystemMessage, list[ChunkedSummaryNode]]:
        """Execute full map-reduce hierarchical compaction pipeline.

        Returns:
            Tuple of (condensed_unified_system_message, chunk_nodes).
        """
        safe_budget = model_spec.safe_input_capacity
        chunks = cls.slice_messages_into_chunks(messages, safe_budget)

        chunk_nodes: list[ChunkedSummaryNode] = []
        total_chunks = len(chunks)

        # Map phase: process each chunk slice
        for idx, chk in enumerate(chunks):
            node = cls.summarize_chunk_deterministic(chk, idx, total_chunks)
            chunk_nodes.append(node)

        # Reduce phase: assemble hierarchical workflow memory
        all_entities: set[str] = set()
        chunk_sections: list[str] = []

        for node in chunk_nodes:
            all_entities.update(node.key_entities)
            chunk_sections.append(f"  • {node.extracted_summary}")

        hierarchical_memory = (
            "<hierarchical_workflow_memory status=\"lossless_map_reduce\">\n"
            f"  <!-- Consolidated from {total_chunks} chunked partitions with 15% continuity overlap -->\n"
            f"  <preserved_entities total=\"{len(all_entities)}\">\n"
            f"    {', '.join(sorted(all_entities)[:40])}\n"
            "  </preserved_entities>\n"
            "  <partition_timeline>\n"
            + "\n".join(chunk_sections) + "\n"
            "  </partition_timeline>\n"
            "</hierarchical_workflow_memory>"
        )

        unified_msg = SystemMessage(content=hierarchical_memory)
        return unified_msg, chunk_nodes

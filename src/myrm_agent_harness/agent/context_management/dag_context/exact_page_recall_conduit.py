# [INPUT]: HierarchicalDagFolder, HierarchicalDagNode, PageRecallResult, TurnRecord
# [OUTPUT]: ExactPageRecallConduit
# [POS]: agent/context_management/dag_context/exact_page_recall_conduit.py

"""Exact page recall conduit enabling on-demand agent drill-down inspection of historical pages.

[INPUT]
- HierarchicalDagFolder, HierarchicalDagNode, TurnRecord, PageRecallResult: Domain models.

[OUTPUT]
- ExactPageRecallConduit: Serves exact historical turn pages without flooding main prompt context.

[POS]
Tool recall conduit in DAG context subsystem fulfilling on-demand historical turn expansion.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from .dag_types import HierarchicalDagNode, PageRecallResult, TurnRecord
from .hierarchical_dag_folder import HierarchicalDagFolder


class ExactPageRecallConduit:
    """Provides targeted page-level and turn-level recall tools without bloating active context."""

    TOKEN_PATTERN: re.Pattern[str] = re.compile(r"[a-zA-Z0-9_\-\./]+", re.IGNORECASE)

    def __init__(self, folder: HierarchicalDagFolder) -> None:
        self._folder = folder

    def recall_page(self, page_id: str, query: str = "") -> PageRecallResult | None:
        """Recall full contents of a specific page node with optional query relevance scoring."""
        pages = self._folder.get_page_nodes()
        target = next((p for p in pages if p.node_id == page_id), None)
        if not target:
            return None

        # Retrieve all raw turns covered by this page
        raw_turns = self._folder.get_raw_turns()
        turns_in_page = [
            t for t in raw_turns
            if t.turn_id in target.child_ids
        ]

        full_page_lines: list[str] = [
            f"# [Expanded History: {target.title}]",
        ]
        for t in turns_in_page:
            full_page_lines.append(f"### Turn {t.turn_id} ({t.role.upper()}):\n{t.content}\n")

        full_text = "\n".join(full_page_lines)
        score = 1.0
        if query.strip():
            query_tokens = [tok.lower() for tok in self.TOKEN_PATTERN.findall(query) if len(tok) >= 2]
            text_lower = full_text.lower()
            matched = sum(1 for q in query_tokens if q in text_lower)
            score = matched / max(1, len(query_tokens))

        return PageRecallResult(
            page_id=target.node_id,
            turn_range=target.turn_range,
            title=target.title,
            content=full_text,
            relevance_score=round(score, 4),
        )

    def expand_turn(self, turn_id: str) -> TurnRecord | None:
        """Fetch the exact verbatim content of a single historical turn by turn_id."""
        raw_turns = self._folder.get_raw_turns()
        return next((t for t in raw_turns if t.turn_id == turn_id), None)

    def generate_tool_specifications(self) -> Sequence[Mapping[str, object]]:
        """Generate OpenAI-compatible tool specifications for page recall and turn expansion."""
        return (
            {
                "type": "function",
                "function": {
                    "name": "session_page_recall",
                    "description": (
                        "Inspect exact, uncompressed historical transcripts from a folded context page. "
                        "Use this when needing specific configurations, error logs, or code from prior turns."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_id": {
                                "type": "string",
                                "description": "The page identifier (e.g. 'page-1', 'page-2') listed in the context skeleton.",
                            },
                            "query": {
                                "type": "string",
                                "description": "Optional keyword or snippet to focus within the page.",
                            },
                        },
                        "required": ["page_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "session_turn_expand",
                    "description": "Retrieve verbatim original content of a specific historical turn by ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "turn_id": {
                                "type": "string",
                                "description": "The turn ID (e.g. 't1', 'turn-12') to expand.",
                            },
                        },
                        "required": ["turn_id"],
                    },
                },
            },
        )

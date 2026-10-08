"""On-demand paged recall meta-tool for archived observations.

[INPUT]
- ContentAddressedStore, ObservationPage: Storage engine and page model from observation_pack.

[OUTPUT]
- ObservationRecallTool: Meta-tool providing deterministic, page-by-page inspection of archived tool results.

[POS]
Native runtime meta-tool enabling LLMs to selectively inspect truncated large outputs on demand.
"""

from __future__ import annotations

from typing import Mapping

from .content_addressed_store import ContentAddressedStore
from .observation_pack_types import ObservationPage


class ObservationRecallTool:
    """Provides recall_observation tool definition and execution handler."""

    def __init__(self, store: ContentAddressedStore) -> None:
        self._store = store

    @property
    def store(self) -> ContentAddressedStore:
        return self._store

    @staticmethod
    def get_tool_spec() -> Mapping[str, object]:
        """Return canonical JSON Schema specification for the recall_observation tool."""
        return {
            "type": "function",
            "function": {
                "name": "recall_observation",
                "description": (
                    "Recall and page through a previously archived large tool observation by its handle ID. "
                    "Use when an observation in the conversation was truncated to inspect exact lines."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "obs_id": {
                            "type": "string",
                            "description": "The observation handle ID (e.g., 'obs_8f2a1b9c...')",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Page number (1-based index). Defaults to 1.",
                            "default": 1,
                        },
                        "page_size": {
                            "type": "integer",
                            "description": "Number of lines per page. Defaults to 100.",
                            "default": 100,
                        },
                    },
                    "required": ["obs_id"],
                },
            },
        }

    def execute(
        self,
        obs_id: str,
        page: int = 1,
        page_size: int = 100,
    ) -> str:
        """Execute the recall tool, returning formatted page slice text."""
        clean_id = obs_id.strip()
        page_slice: ObservationPage | None = self._store.get_page(
            obs_id=clean_id,
            page=page,
            page_size=page_size,
        )

        if page_slice is None:
            return f"[Error: Observation '{clean_id}' not found in local store. Verify the handle ID.]"

        start_line = (page_slice.page - 1) * page_slice.page_size + 1
        end_line = start_line + len(page_slice.lines) - 1
        if page_slice.total_lines == 0:
            start_line = 0
            end_line = 0

        header = (
            f"[Observation {page_slice.obs_id} | Page {page_slice.page}/{page_slice.total_pages} "
            f"(Lines {start_line}-{end_line} of {page_slice.total_lines})]"
        )

        formatted_lines = [
            f"{start_line + idx:5d} | {line}"
            for idx, line in enumerate(page_slice.lines)
        ]

        footer_notes: list[str] = []
        if page_slice.has_more:
            footer_notes.append(
                f"[More lines available. Call recall_observation('{clean_id}', page={page_slice.page + 1}) to continue]"
            )
        else:
            footer_notes.append("[End of observation]")

        return "\n".join([header] + formatted_lines + footer_notes)

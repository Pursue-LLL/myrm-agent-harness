"""Unified facade suite for living scratchpad working memory and bidirectional context conduit.

[INPUT]
- LivingScratchpadConfig, ScratchpadConduitInjection, ScratchpadDocument, ScratchpadPatchOp, ScratchpadScope: Domain types.
- LivingScratchpadDocumentManager: Document storage and checklist parsing.
- ScratchpadBidirectionalPatcher: Atomic co-editing patch resolution engine.
- ScratchpadContextConduit: Context injection and actionable checklist prompt extractor.

[OUTPUT]
- LivingScratchpadWorkingMemoryAndBiDirectionalContextConduitSuite: Cohesive facade coordinating
  human-agent scratchpad co-editing, version management, and LLM context conduit injection.

[POS]
Top-level entry point for living scratchpad working memory in context management.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .living_scratchpad_document_manager import LivingScratchpadDocumentManager
from .scratchpad_bidirectional_patcher import ScratchpadBidirectionalPatcher
from .scratchpad_context_conduit import ScratchpadContextConduit
from .scratchpad_types import (
    LivingScratchpadConfig,
    ScratchpadConduitInjection,
    ScratchpadDocument,
    ScratchpadPatchOp,
    ScratchpadScope,
)


class LivingScratchpadWorkingMemoryAndBiDirectionalContextConduitSuite:
    """Industrial facade coordinating living scratchpad state, co-editing, and context injection."""

    def __init__(
        self,
        config: LivingScratchpadConfig | None = None,
        doc_manager: LivingScratchpadDocumentManager | None = None,
        patcher: ScratchpadBidirectionalPatcher | None = None,
        conduit: ScratchpadContextConduit | None = None,
    ) -> None:
        self._config = config or LivingScratchpadConfig()
        self._doc_manager = doc_manager or LivingScratchpadDocumentManager(self._config)
        self._patcher = patcher or ScratchpadBidirectionalPatcher(self._doc_manager)
        self._conduit = conduit or ScratchpadContextConduit(self._config)

    @property
    def config(self) -> LivingScratchpadConfig:
        """Returns the active configuration."""
        return self._config

    @property
    def doc_manager(self) -> LivingScratchpadDocumentManager:
        """Returns the internal document manager."""
        return self._doc_manager

    @property
    def patcher(self) -> ScratchpadBidirectionalPatcher:
        """Returns the internal patcher."""
        return self._patcher

    @property
    def conduit(self) -> ScratchpadContextConduit:
        """Returns the internal context conduit."""
        return self._conduit

    @property
    def total_documents_count(self) -> int:
        """Returns total active scratchpad documents count."""
        return self._doc_manager.total_documents_count

    def get_or_create_session_pad(
        self,
        session_id: str,
        title: str | None = None,
        initial_content: str = "",
        timestamp: float | None = None,
    ) -> ScratchpadDocument:
        """Retrieves or creates a session-scoped scratchpad document."""
        return self._doc_manager.get_or_create_session_pad(
            session_id=session_id,
            title=title,
            initial_content=initial_content,
            timestamp=timestamp,
        )

    def get_or_create_global_pad(
        self,
        global_id: str = "default_global",
        title: str | None = None,
        initial_content: str = "",
        timestamp: float | None = None,
    ) -> ScratchpadDocument:
        """Retrieves or creates a global workspace scratchpad document."""
        return self._doc_manager.get_or_create_global_pad(
            global_id=global_id,
            title=title,
            initial_content=initial_content,
            timestamp=timestamp,
        )

    def apply_patch(
        self,
        doc: ScratchpadDocument,
        op: ScratchpadPatchOp,
        payload: str,
        target_line: int | None = None,
        expected_version: int | None = None,
        timestamp: float | None = None,
    ) -> ScratchpadDocument:
        """Applies an atomic mutation to the document, returning the new versioned document."""
        return self._patcher.apply_patch(
            doc=doc,
            op=op,
            payload=payload,
            target_line=target_line,
            expected_version=expected_version,
            timestamp=timestamp,
        )

    def append_todo_item(
        self,
        doc: ScratchpadDocument,
        todo_text: str,
        is_completed: bool = False,
        timestamp: float | None = None,
    ) -> ScratchpadDocument:
        """Appends a markdown checkbox todo item to the scratchpad."""
        return self._patcher.append_todo_item(
            doc=doc,
            todo_text=todo_text,
            is_completed=is_completed,
            timestamp=timestamp,
        )

    def toggle_todo(
        self,
        doc: ScratchpadDocument,
        target_line: int | None = None,
        timestamp: float | None = None,
    ) -> ScratchpadDocument:
        """Toggles completion state of a todo item at the specified line number."""
        return self._patcher.apply_patch(
            doc=doc,
            op=ScratchpadPatchOp.TOGGLE_TODO,
            payload="",
            target_line=target_line,
            timestamp=timestamp,
        )

    def serialize_injection(self, doc: ScratchpadDocument) -> ScratchpadConduitInjection:
        """Formats the scratchpad into an ultra-dense XML block for context injection."""
        return self._conduit.serialize_injection(doc)

    def extract_pending_todos_prompt(self, doc: ScratchpadDocument) -> str:
        """Extracts unchecked todos into an actionable prompt instruction for the agent."""
        return self._conduit.extract_pending_todos_prompt(doc)

    def inject_into_system_prompt(
        self,
        base_system_prompt: str,
        doc: ScratchpadDocument,
    ) -> str:
        """Appends the living scratchpad block cleanly to the system prompt."""
        return self._conduit.inject_into_system_prompt(base_system_prompt, doc)

    def delete_session_pad(self, session_id: str) -> bool:
        """Deletes a session pad from storage."""
        return self._doc_manager.delete_session_pad(session_id)

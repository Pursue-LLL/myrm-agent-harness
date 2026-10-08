"""Living scratchpad document manager storing and parsing markdown session and global pads.

[INPUT]
- LivingScratchpadConfig, ScratchpadDocument, ScratchpadScope, ScratchpadTodoItem: Domain models.

[OUTPUT]
- LivingScratchpadDocumentManager: Manages document state, version increments, and todo parsing.

[POS]
Document persistence and Markdown checklist parsing layer for living scratchpad working memory.
"""

from __future__ import annotations

import re
import time
from typing import Mapping, Sequence

from .scratchpad_types import (
    LivingScratchpadConfig,
    ScratchpadDocument,
    ScratchpadScope,
    ScratchpadTodoItem,
)

_TODO_PATTERN = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s*(.*)$")


class LivingScratchpadDocumentManager:
    """Manages session-scoped and global-scoped living scratchpads with todo introspection."""

    def __init__(self, config: LivingScratchpadConfig | None = None) -> None:
        self._config = config or LivingScratchpadConfig()
        # session_id -> ScratchpadDocument
        self._session_pads: dict[str, ScratchpadDocument] = {}
        # global_id -> ScratchpadDocument
        self._global_pads: dict[str, ScratchpadDocument] = {}

    def get_or_create_session_pad(
        self,
        session_id: str,
        title: str | None = None,
        initial_content: str = "",
        timestamp: float | None = None,
    ) -> ScratchpadDocument:
        """Retrieves existing session pad or initializes a new blank document."""
        if session_id in self._session_pads:
            return self._session_pads[session_id]

        now = timestamp if timestamp is not None else time.time()
        effective_title = title or f"Session Scratchpad ({session_id[:8]})"
        todos = self.parse_todos(initial_content)

        doc = ScratchpadDocument(
            scratchpad_id=f"pad_sess_{session_id}",
            scope=ScratchpadScope.SESSION_SCOPED,
            session_id=session_id,
            title=effective_title,
            content=initial_content[:self._config.max_content_chars],
            version=1,
            updated_at=now,
            todos=todos,
        )
        self._session_pads[session_id] = doc
        return doc

    def get_or_create_global_pad(
        self,
        global_id: str = "default_global",
        title: str | None = None,
        initial_content: str = "",
        timestamp: float | None = None,
    ) -> ScratchpadDocument:
        """Retrieves existing global workspace pad or initializes a new document."""
        if global_id in self._global_pads:
            return self._global_pads[global_id]

        now = timestamp if timestamp is not None else time.time()
        effective_title = title or "Global Workspace Scratchpad"
        todos = self.parse_todos(initial_content)

        doc = ScratchpadDocument(
            scratchpad_id=f"pad_glob_{global_id}",
            scope=ScratchpadScope.GLOBAL_SCOPED,
            session_id=None,
            title=effective_title,
            content=initial_content[:self._config.max_content_chars],
            version=1,
            updated_at=now,
            todos=todos,
        )
        self._global_pads[global_id] = doc
        return doc

    def update_document(
        self,
        doc: ScratchpadDocument,
        new_content: str,
        new_title: str | None = None,
        timestamp: float | None = None,
    ) -> ScratchpadDocument:
        """Applies content mutation, bumps version monotonically, and recalculates todos."""
        now = timestamp if timestamp is not None else time.time()
        bounded_content = new_content[:self._config.max_content_chars]
        todos = self.parse_todos(bounded_content)

        updated_doc = ScratchpadDocument(
            scratchpad_id=doc.scratchpad_id,
            scope=doc.scope,
            session_id=doc.session_id,
            title=new_title or doc.title,
            content=bounded_content,
            version=doc.version + 1,
            updated_at=now,
            todos=todos,
        )

        if doc.scope == ScratchpadScope.SESSION_SCOPED and doc.session_id:
            self._session_pads[doc.session_id] = updated_doc
        else:
            self._global_pads[doc.scratchpad_id] = updated_doc

        return updated_doc

    def parse_todos(self, content: str) -> tuple[ScratchpadTodoItem, ...]:
        """Scans lines for Markdown checkboxes (- [ ] / - [x]) and extracts line positions."""
        lines = content.splitlines()
        todos: list[ScratchpadTodoItem] = []

        for idx, line in enumerate(lines, start=1):
            match = _TODO_PATTERN.match(line)
            if match:
                marker = match.group(1).strip()
                item_text = match.group(2).strip()
                is_completed = marker.lower() == "x"
                todos.append(
                    ScratchpadTodoItem(
                        text=item_text,
                        is_completed=is_completed,
                        line_number=idx,
                    )
                )

        return tuple(todos)

    def delete_session_pad(self, session_id: str) -> bool:
        """Deletes a session pad from storage."""
        if session_id in self._session_pads:
            del self._session_pads[session_id]
            return True
        return False

    @property
    def total_documents_count(self) -> int:
        """Returns total active documents count across session and global stores."""
        return len(self._session_pads) + len(self._global_pads)

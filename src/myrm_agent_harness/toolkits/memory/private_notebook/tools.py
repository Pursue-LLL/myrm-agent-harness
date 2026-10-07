"""[POS]: src/myrm_agent_harness/toolkits/memory/private_notebook/tools.py
[INPUT]: Tool invocation arguments for history inspection, note taking, and context switching.
[OUTPUT]: PrivateNotebookToolKit providing the 10 autonomous tools (History 4, Notes 5, NewContext 1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import ModelPrivateNotebookManager


class PrivateNotebookToolKit:
    """Encapsulates the 10 autonomous tools for model private notes, history recall, and context handover."""

    def __init__(self, manager: ModelPrivateNotebookManager) -> None:
        self._manager = manager

    # -------------------------------------------------------------------------
    # Notes Group (5 Tools)
    # -------------------------------------------------------------------------

    def list_notes(self) -> list[dict[str, object]]:
        """List all active notes in the model private notebook with size and line counts."""
        metas = self._manager.storage.list_notes()
        return [
            {
                "title": m.title,
                "char_count": m.char_count,
                "line_count": m.line_count,
                "updated_at": m.updated_at.isoformat(),
            }
            for m in metas
        ]

    def read_note(self, title: str) -> dict[str, object]:
        """Read full markdown content of a private note by its title."""
        note = self._manager.storage.read_note(title)
        if note is None:
            return {"error": f"Note '{title}' not found", "found": False}
        return {
            "title": note.title,
            "content": note.content,
            "updated_at": note.updated_at.isoformat(),
            "found": True,
        }

    def append_note(self, title: str, content: str) -> dict[str, object]:
        """Append facts, lessons learned, or intermediate findings to a private note."""
        note = self._manager.storage.append_note(title, content)
        return {
            "status": "success",
            "title": note.title,
            "updated_at": note.updated_at.isoformat(),
            "total_length": len(note.content),
        }

    def rewrite_note(self, title: str, content: str) -> dict[str, object]:
        """Atomically overwrite or rectify the contents of an existing note."""
        note = self._manager.storage.rewrite_note(title, content)
        return {
            "status": "success",
            "title": note.title,
            "updated_at": note.updated_at.isoformat(),
            "total_length": len(note.content),
        }

    def search_notes(self, query: str) -> list[dict[str, object]]:
        """Search across all private notes by keywords and retrieve relevant context snippets."""
        hits = self._manager.storage.search_notes(query)
        return [
            {
                "title": h.title,
                "score": h.score,
                "snippet": h.snippet,
            }
            for h in hits
        ]

    # -------------------------------------------------------------------------
    # History Group (4 Tools)
    # -------------------------------------------------------------------------

    def list_history_contexts(self) -> list[dict[str, object]]:
        """List all archived previous context windows and their turn statistics."""
        contexts = self._manager.history.list_contexts()
        return [
            {
                "context_id": c.context_id,
                "title": c.title,
                "turn_count": c.turn_count,
                "created_at": c.created_at.isoformat(),
            }
            for c in contexts
        ]

    def list_history_entries(self, context_id: str) -> list[dict[str, object]]:
        """List all conversation and tool interaction turns within a specific historical context."""
        entries = self._manager.history.list_entries(context_id)
        return [
            {
                "context_id": e.context_id,
                "turn_index": e.turn_index,
                "role": e.role,
                "content_preview": e.content[:160],
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ]

    def read_history_entry(self, context_id: str, turn_index: int) -> dict[str, object]:
        """Read the full raw text or command execution result of an archived historical turn."""
        entry = self._manager.history.read_entry(context_id, turn_index)
        if entry is None:
            return {
                "error": f"Entry index {turn_index} not found in context {context_id}",
                "found": False,
            }
        return {
            "context_id": entry.context_id,
            "turn_index": entry.turn_index,
            "role": entry.role,
            "content": entry.content,
            "created_at": entry.created_at.isoformat(),
            "found": True,
        }

    def search_history(self, query: str, max_results: int = 10) -> list[dict[str, object]]:
        """Search past hours of command executions, code diffs, and error outputs across contexts."""
        results = self._manager.history.search_history(query, max_results=max_results)
        return [
            {
                "context_id": r.context_id,
                "turn_index": r.turn_index,
                "role": r.role,
                "snippet": r.content[:240],
                "created_at": r.created_at.isoformat(),
            }
            for r in results
        ]

    # -------------------------------------------------------------------------
    # Context Switching Tool (1 Tool)
    # -------------------------------------------------------------------------

    def new_context(self, summary_reason: str) -> dict[str, object]:
        """Smoothly rotate to a clean new context window while retaining sandbox files and notes."""
        result = self._manager.switch_to_new_context(summary_reason)
        return {
            "status": result.status,
            "new_context_id": result.new_context_id,
            "previous_context_id": result.previous_context_id,
            "carried_notes_count": result.carried_notes_count,
            "message": f"Switched to clean context. {result.carried_notes_count} notes carried over.",
        }

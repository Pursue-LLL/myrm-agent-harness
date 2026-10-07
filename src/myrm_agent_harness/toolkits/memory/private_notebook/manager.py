"""[POS]: src/myrm_agent_harness/toolkits/memory/private_notebook/manager.py
[INPUT]: Sandbox workspace directory, initial context ID, note updates, and rotation requests.
[OUTPUT]: ModelPrivateNotebookManager orchestrating storage, history index, tools, and context switching.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from threading import Lock

from .history_manager import HistoryContextManager
from .models import NewContextResult
from .storage import LocalInspectableNoteStorage
from .tools import PrivateNotebookToolKit


class ModelPrivateNotebookManager:
    """Unified orchestrator for local inspectable private notes, cross-context recall, and seamless rotation."""

    def __init__(
        self,
        workspace_dir: Path | str,
        initial_context_id: str | None = None,
    ) -> None:
        base_path = Path(workspace_dir)
        notes_path = base_path / ".myrm" / "agent_notes"
        self._storage = LocalInspectableNoteStorage(notes_path)
        self._history = HistoryContextManager()
        self._current_context_id = initial_context_id or f"ctx_{uuid.uuid4().hex[:8]}"
        self._lock = Lock()
        self._toolkit = PrivateNotebookToolKit(self)

    @property
    def storage(self) -> LocalInspectableNoteStorage:
        """Accesses the local inspectable notes filesystem storage."""
        return self._storage

    @property
    def history(self) -> HistoryContextManager:
        """Accesses the archived historical context manager."""
        return self._history

    @property
    def tools(self) -> PrivateNotebookToolKit:
        """Accesses the 10-tool autonomous toolkit."""
        return self._toolkit

    @property
    def current_context_id(self) -> str:
        """Retrieves the active conversation context window identifier."""
        with self._lock:
            return self._current_context_id

    def record_turn(self, role: str, content: str) -> None:
        """Convenience method recording an ongoing turn into current context history."""
        with self._lock:
            ctx_id = self._current_context_id
        self._history.record_entry(ctx_id, role, content)

    def switch_to_new_context(
        self,
        summary_reason: str,
        custom_new_id: str | None = None,
    ) -> NewContextResult:
        """Rotates active context to a clean new window while keeping sandbox state and notes intact."""
        with self._lock:
            prev_id = self._current_context_id
            new_id = custom_new_id or f"ctx_{uuid.uuid4().hex[:8]}"
            self._current_context_id = new_id

        # Auto-record handover note in private storage
        handover_entry = (
            f"### Context Handover: {prev_id} -> {new_id}\n"
            f"- Reason: {summary_reason.strip()}\n"
            f"- Status: Active in clean window with persistent workspace and notes.\n"
        )
        self._storage.append_note("context_handovers", handover_entry)

        active_notes = self._storage.list_notes()
        return NewContextResult(
            new_context_id=new_id,
            previous_context_id=prev_id,
            carried_notes_count=len(active_notes),
            status="ready",
        )

    def auto_compact_fallback(self, unsummarized_turns: list[str]) -> str:
        """Secondary fallback compression when context exceeds physical budget without notes."""
        if not unsummarized_turns:
            return "No previous turns to compact."
        joined = "\n".join(unsummarized_turns[-6:])
        return f"[Fallback Compact Summary of last turns]:\n{joined[:400]}"

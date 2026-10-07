"""[POS]: src/myrm_agent_harness/toolkits/memory/private_notebook/storage.py
[INPUT]: Filesystem root path, note titles, markdown contents, and query keywords.
[OUTPUT]: LocalInspectableNoteStorage persisting human-inspectable markdown notes under .myrm/agent_notes.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from .models import NoteEntry, NoteMetadata, NoteSearchResult


def sanitize_filename(title: str) -> str:
    """Normalizes title into a safe filename without dangerous traversal characters."""
    cleaned = re.sub(r"[^\w\s-]", "", title).strip().lower()
    return re.sub(r"[-\s]+", "_", cleaned) or "untitled"


class LocalInspectableNoteStorage:
    """Thread-safe, human-inspectable filesystem storage for model private notes in Markdown."""

    def __init__(self, notes_dir: Path | str) -> None:
        self._notes_dir = Path(notes_dir)
        self._notes_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    @property
    def notes_dir(self) -> Path:
        """Root directory on local disk or sandbox volume holding markdown notes."""
        return self._notes_dir

    def _get_path(self, title: str) -> Path:
        safe_name = sanitize_filename(title)
        return self._notes_dir / f"{safe_name}.md"

    def list_notes(self) -> list[NoteMetadata]:
        """Lists all existing notes with their size, line count, and modification timestamp."""
        with self._lock:
            if not self._notes_dir.exists():
                return []
            metas: list[NoteMetadata] = []
            for filepath in sorted(self._notes_dir.glob("*.md")):
                if not filepath.is_file():
                    continue
                try:
                    text = filepath.read_text(encoding="utf-8")
                    mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=UTC)
                    lines = text.splitlines()
                    metas.append(
                        NoteMetadata(
                            title=filepath.stem,
                            char_count=len(text),
                            line_count=len(lines),
                            updated_at=mtime,
                            tags=[],
                        )
                    )
                except OSError:
                    continue
            return metas

    def read_note(self, title: str) -> NoteEntry | None:
        """Reads full text content of a note by title."""
        filepath = self._get_path(title)
        with self._lock:
            if not filepath.is_file():
                return None
            try:
                text = filepath.read_text(encoding="utf-8")
                mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=UTC)
                return NoteEntry(
                    title=filepath.stem,
                    content=text,
                    updated_at=mtime,
                    tags=[],
                )
            except OSError:
                return None

    def append_note(
        self,
        title: str,
        content_to_append: str,
        tags: list[str] | None = None,
    ) -> NoteEntry:
        """Appends content to an existing note, or creates a new note if it does not exist."""
        filepath = self._get_path(title)
        with self._lock:
            existing = ""
            if filepath.is_file():
                try:
                    existing = filepath.read_text(encoding="utf-8")
                except OSError:
                    existing = ""

            delimiter = "\n\n" if existing and not existing.endswith("\n\n") else ""
            new_text = f"{existing}{delimiter}{content_to_append.strip()}\n"
            filepath.write_text(new_text, encoding="utf-8")
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=UTC)

            return NoteEntry(
                title=filepath.stem,
                content=new_text,
                updated_at=mtime,
                tags=tags or [],
            )

    def rewrite_note(
        self,
        title: str,
        new_content: str,
        tags: list[str] | None = None,
    ) -> NoteEntry:
        """Atomically overwrites note content, supporting model updates and human corrections."""
        filepath = self._get_path(title)
        with self._lock:
            content_normalized = f"{new_content.strip()}\n"
            filepath.write_text(content_normalized, encoding="utf-8")
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=UTC)

            return NoteEntry(
                title=filepath.stem,
                content=content_normalized,
                updated_at=mtime,
                tags=tags or [],
            )

    def delete_note(self, title: str) -> bool:
        """Removes a note file by title. Returns True if deleted."""
        filepath = self._get_path(title)
        with self._lock:
            if filepath.is_file():
                try:
                    filepath.unlink()
                    return True
                except OSError:
                    return False
            return False

    def search_notes(self, query: str) -> list[NoteSearchResult]:
        """Searches across all note titles and bodies using keyword token matching."""
        terms = [t.lower() for t in query.strip().split() if t.strip()]
        if not terms:
            return []

        results: list[NoteSearchResult] = []
        with self._lock:
            for filepath in sorted(self._notes_dir.glob("*.md")):
                if not filepath.is_file():
                    continue
                try:
                    text = filepath.read_text(encoding="utf-8")
                except OSError:
                    continue

                text_lower = text.lower()
                stem_lower = filepath.stem.lower()

                matched_count = sum(
                    1 for term in terms if term in stem_lower or term in text_lower
                )
                if matched_count == 0:
                    continue

                score = matched_count / len(terms)

                # Extract surrounding snippet around first match
                first_term = terms[0]
                idx = text_lower.find(first_term)
                if idx >= 0:
                    start = max(0, idx - 40)
                    end = min(len(text), idx + len(first_term) + 80)
                    snippet = text[start:end].replace("\n", " ").strip()
                else:
                    snippet = text[:120].replace("\n", " ").strip()

                results.append(
                    NoteSearchResult(
                        title=filepath.stem,
                        score=round(score, 2),
                        snippet=snippet,
                    )
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results

"""Atomic incremental research chapter draft storage engine.

Persists intermediate research chapter outputs to disk or sandbox volumes using
atomic temporary writes and replacements, guaranteeing zero data corruption across crashes.

[OUTPUT]
- IncrementalDraftStore: Atomically saves, loads, and stitches intermediate chapter drafts.

[INPUT]
- __future__
- json
- os
- tempfile
- pathlib

[OUTPUT]
- IncrementalDraftStore

[POS]
Atomic incremental research chapter draft storage engine.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from myrm_agent_harness.runtime.research_checkpoint.checkpoint_types import (
    ResearchChapterDraft,
)


class IncrementalDraftStore:
    """Manages atomic chapter draft persistence and final document assembly."""

    def __init__(self, storage_root: Path | str | None = None) -> None:
        self.storage_root: Path = (
            Path(storage_root).resolve()
            if storage_root
            else Path.cwd() / ".context" / "research_drafts"
        )
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _task_draft_dir(self, task_id: str) -> Path:
        """Get or create the isolated drafts directory for a specific task."""
        d = self.storage_root / task_id / "drafts"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_chapter_draft(
        self,
        task_id: str,
        draft: ResearchChapterDraft,
    ) -> Path:
        """Atomically persist a chapter draft using a temporary file and atomic replace."""
        target_dir = self._task_draft_dir(task_id)
        final_path = target_dir / f"chapter_{draft.chapter_index:03d}.json"

        # Serialize payload
        payload_bytes = json.dumps(
            draft.to_dict(),
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")

        # Write to temporary file in the same directory to allow atomic rename
        with tempfile.NamedTemporaryFile(
            dir=target_dir,
            prefix=f"tmp_ch{draft.chapter_index}_",
            delete=False,
        ) as tmp:
            tmp.write(payload_bytes)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)

        os.replace(tmp_path, final_path)
        return final_path

    def load_chapter_draft(
        self,
        task_id: str,
        chapter_index: int,
    ) -> ResearchChapterDraft | None:
        """Load a specific chapter draft from disk if present."""
        path = self._task_draft_dir(task_id) / f"chapter_{chapter_index:03d}.json"
        if not path.is_file():
            return None

        data = json.loads(path.read_text(encoding="utf-8"))
        return ResearchChapterDraft.from_dict(data)

    def get_all_drafts(self, task_id: str) -> tuple[ResearchChapterDraft, ...]:
        """Retrieve all materialized chapter drafts for a task in topological index order."""
        target_dir = self._task_draft_dir(task_id)
        drafts: list[ResearchChapterDraft] = []

        for p in sorted(target_dir.glob("chapter_*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                drafts.append(ResearchChapterDraft.from_dict(data))
            except Exception:
                continue

        drafts.sort(key=lambda d: d.chapter_index)
        return tuple(drafts)

    def assemble_final_document(
        self,
        task_id: str,
        report_title: str = "Deep Research Final Report",
    ) -> str:
        """Stitch all available completed chapter drafts into a unified Markdown document."""
        drafts = self.get_all_drafts(task_id)
        if not drafts:
            return f"# {report_title}\n\n*(No completed chapter drafts available)*"

        lines: list[str] = [
            f"# {report_title}",
            "",
            "## Table of Contents",
        ]

        for d in drafts:
            slug = d.title.lower().replace(" ", "-")
            lines.append(f"- [Chapter {d.chapter_index}: {d.title}](#{slug})")

        lines.append("\n---\n")

        all_sources: list[str] = []
        for d in drafts:
            lines.append(f"## Chapter {d.chapter_index}: {d.title}\n")
            lines.append(d.content_markdown.strip())
            lines.append("")
            all_sources.extend(d.sources_cited)

        if all_sources:
            lines.append("## References & Sources Cited")
            unique_sources = sorted(set(all_sources))
            for idx, src in enumerate(unique_sources, 1):
                lines.append(f"{idx}. {src}")

        return "\n".join(lines)

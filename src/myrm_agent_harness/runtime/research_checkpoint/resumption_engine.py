"""Zero-waste research task resumption and context injection engine.

Translates persistent checkpoints and intermediate chapter drafts into clean resumption
plans, ensuring the agent loop continues precisely from the interrupted chapter without
wasting tokens or repeating previously completed research work.

[OUTPUT]
- ResearchResumptionEngine: Computes resumption plans and synthesizes prompt injections.

[INPUT]
- __future__

[OUTPUT]
- ResearchResumptionEngine

[POS]
Zero-waste research task resumption and context injection engine.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.research_checkpoint.checkpoint_ledger import (
    ResearchCheckpointLedger,
)
from myrm_agent_harness.runtime.research_checkpoint.checkpoint_types import (
    ResumptionPlan,
)
from myrm_agent_harness.runtime.research_checkpoint.draft_store import (
    IncrementalDraftStore,
)


class ResearchResumptionEngine:
    """Orchestrates zero-waste research task resumption from checkpoints."""

    def __init__(
        self,
        ledger: ResearchCheckpointLedger,
        draft_store: IncrementalDraftStore,
    ) -> None:
        self.ledger: ResearchCheckpointLedger = ledger
        self.draft_store: IncrementalDraftStore = draft_store

    def prepare_resumption(self, task_id: str) -> ResumptionPlan:
        """Compute the resumption plan and context prompt for an interrupted task."""
        checkpoint = self.ledger.get_latest_checkpoint(task_id)
        if checkpoint is None:
            return ResumptionPlan(
                task_id=task_id,
                checkpoint_id="",
                can_resume=False,
                next_chapter_index=None,
                completed_chapters_count=0,
                pending_chapters_count=0,
                context_injection_prompt="",
            )

        if checkpoint.is_finished or not checkpoint.pending_chapters:
            return ResumptionPlan(
                task_id=task_id,
                checkpoint_id=checkpoint.checkpoint_id,
                can_resume=False,
                next_chapter_index=None,
                completed_chapters_count=len(checkpoint.completed_chapters),
                pending_chapters_count=0,
                context_injection_prompt="Task is already fully completed.",
            )

        next_chapter = checkpoint.pending_chapters[0]
        drafts = self.draft_store.get_all_drafts(task_id)

        # Synthesize context injection prompt summarizing already-completed research chapters
        lines: list[str] = [
            f"### 📑 Resuming Interrupted Long-Horizon Research Task: {task_id}",
            f"- **Checkpoint ID**: `{checkpoint.checkpoint_id}`",
            f"- **Completed Chapters**: {list(checkpoint.completed_chapters)} ({len(drafts)} drafts persisted on disk)",
            f"- **Pending Chapters**: {list(checkpoint.pending_chapters)}",
            f"- **Immediate Target**: Chapter {next_chapter}",
            "",
            "#### 🔒 Established Prior Research Knowledge (DO NOT RE-RUN OR RE-WRITE):",
        ]

        for d in drafts:
            # Provide title, sources, and a concise summary preview of the established chapter
            summary_preview = (
                d.content_markdown[:300] + "..."
                if len(d.content_markdown) > 300
                else d.content_markdown
            )
            clean_preview = summary_preview.replace("\n", " ").strip()
            lines.append(
                f"1. **Chapter {d.chapter_index}: {d.title}**"
                f"\n   - *Summary*: {clean_preview}"
                f"\n   - *Sources*: {list(d.sources_cited)}"
            )

        lines.extend(
            [
                "",
                "#### ⚡ Directive for Resumption:",
                f"Proceed directly to researching and drafting **Chapter {next_chapter}**.",
                "Do NOT re-execute tools or re-draft any previously completed chapters listed above.",
            ]
        )

        return ResumptionPlan(
            task_id=task_id,
            checkpoint_id=checkpoint.checkpoint_id,
            can_resume=True,
            next_chapter_index=next_chapter,
            completed_chapters_count=len(checkpoint.completed_chapters),
            pending_chapters_count=len(checkpoint.pending_chapters),
            context_injection_prompt="\n".join(lines),
        )
